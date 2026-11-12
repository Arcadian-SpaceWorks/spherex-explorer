"""Read only the bytes needed for one photometric measurement from a full SPHEREx exposure.

A Level 2 product is about 70 MB and a sky point is covered by hundreds of them. The products are
public on the AWS Open Data mirror of the IRSA archive, which honours HTTP range requests, so each
exposure costs a few small requests (headers, 23 image rows of three planes, the wavelength table:
about 0.4 MB) instead of a download or an IRSA cutout job.

Nothing here guesses a layout: every HDU offset is derived from the headers that were read, and each
header is checked for the expected extension name before its data is used.
"""
import re

import numpy as np
import requests
from astropy.io import fits

from ..fits_image import wavelength_at
from .photometry import locate, measure, window

MIRROR = 'https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/'
# Archive `uri` values look like ibe/data/spherex/qr2/level2/<week>/<version>/<n>/<file>.fits
URI = re.compile(r'^ibe/data/spherex/(qr\d+/level2/[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)*\.fits)$')
BLOCK = 2880
HEADER_GUESS = 12 * BLOCK
MAX_HEADER = 80 * BLOCK
MAX_SPAN = 4 * 1024 * 1024  # No single read for one measurement may exceed this.
DTYPES = {32: '>i4', -32: '>f4', 16: '>i2', 8: 'u1', 64: '>i8', -64: '>f8'}
EMPTY_PRIMARY = fits.PrimaryHDU().header.tostring().encode('ascii')


class RemoteError(Exception):
    """The exposure could not be read (network, missing object or unexpected file structure)."""


def mirror_url(uri):
    match = URI.match(uri or '')
    if not match or '..' in uri:
        raise RemoteError('Archive path is not a SPHEREx Level 2 product.')
    return MIRROR + match[1]


class RangeReader:
    """Byte ranges of one remote object. `fetch(url, headers)` is injectable for tests."""

    def __init__(self, session, url, timeout=(10, 30)):
        self.session, self.url, self.timeout = session, url, timeout
        self.size = None
        self.bytes_read = 0

    def _get(self, header):
        last = None
        for _ in range(2):  # One retry for transient network errors.
            try:
                response = self.session.get(self.url, headers={'Range': header}, timeout=self.timeout,
                                            allow_redirects=False)
                if response.status_code != 206:
                    raise RemoteError(f'Mirror answered HTTP {response.status_code} to a range request.')
                total = response.headers.get('Content-Range', '').rpartition('/')[2]
                if total.isdigit():
                    self.size = int(total)
                self.bytes_read += len(response.content)
                return response.content
            except requests.RequestException as exc:
                last = exc
        raise RemoteError('The exposure could not be read from the mirror.') from last

    def read(self, start, length):
        if length <= 0 or length > MAX_SPAN:
            raise RemoteError('Refusing an unexpectedly large read.')
        data = self._get(f'bytes={start}-{start + length - 1}')
        if len(data) != length and (self.size is None or start + len(data) != self.size):
            raise RemoteError('Short read from the mirror.')
        return data

    def tail(self, length):
        return self._get(f'bytes=-{length}')


def header_length(buffer):
    """Bytes of the first complete FITS header in `buffer` (multiple of 2880), or None."""
    for offset in range(0, len(buffer) - 79, 80):
        if buffer[offset:offset + 80] == b'END' + b' ' * 77:
            return (offset // BLOCK + 1) * BLOCK
    return None


def read_header(reader, offset, guess=HEADER_GUESS, buffer=b''):
    """(header, header_bytes, bytes already read after the header)."""
    while True:
        if len(buffer) >= BLOCK:
            length = header_length(buffer)
            if length is not None:
                return fits.Header.fromstring(buffer[:length].decode('ascii', 'replace')), length, buffer[length:]
        if len(buffer) >= MAX_HEADER:
            raise RemoteError('FITS header not terminated within the expected size.')
        more = reader.read(offset + len(buffer), guess)
        if not more:
            raise RemoteError('Unexpected end of file while reading a header.')
        buffer += more


def data_bytes(header):
    """Unpadded size of an HDU data unit, from the standard keywords."""
    naxis = int(header.get('NAXIS', 0))
    if naxis == 0:
        return 0
    count = 1
    for axis in range(1, naxis + 1):
        count *= int(header[f'NAXIS{axis}'])
    return abs(int(header['BITPIX'])) // 8 * int(header.get('GCOUNT', 1)) * (int(header.get('PCOUNT', 0)) + count)


def padded(size):
    return -(-size // BLOCK) * BLOCK


def read_rows(reader, data_offset, header, rows, columns):
    """A [rows, columns] window of an uncompressed 2D image HDU, read as whole-row byte spans."""
    width, dtype = int(header['NAXIS1']), np.dtype(DTYPES[int(header['BITPIX'])])
    raw = reader.read(data_offset + rows.start * width * dtype.itemsize, (rows.stop - rows.start) * width * dtype.itemsize)
    data = np.frombuffer(raw, dtype=dtype).reshape(rows.stop - rows.start, width)[:, columns]
    scale, zero = header.get('BSCALE', 1), header.get('BZERO', 0)
    return data * scale + zero if (scale, zero) != (1, 0) else data


def read_compressed_rows(reader, hdu_offset, header, header_len, after, rows, columns):
    """A window of a tile-compressed image whose tiles are whole rows (SPHEREx QR3 FLAGS).

    Reads the row descriptor table, then only the heap bytes of the wanted rows, and hands astropy a
    small compressed HDU made of exactly those tiles, so the official decoder does the decompression.
    """
    width, height = int(header['ZNAXIS1']), int(header['ZNAXIS2'])
    if (header.get('ZNAXIS') != 2 or int(header.get('ZTILE1', width)) != width or int(header.get('ZTILE2', 1)) != 1
            or header.get('TFIELDS') != 1 or not str(header.get('TFORM1', '')).startswith('1P')
            or int(header['NAXIS1']) != 8 or int(header['NAXIS2']) != height):
        raise RemoteError('Unsupported compressed image layout.')
    table_offset, table_size = hdu_offset + header_len, 8 * height
    table = after[:table_size]
    if len(table) < table_size:
        table += reader.read(table_offset + len(table), table_size - len(table))
    descriptors = np.frombuffer(table, dtype='>i4').reshape(height, 2)[rows]  # (length, heap offset)
    start = int(descriptors[:, 1].min())
    stop = int((descriptors[:, 1] + descriptors[:, 0]).max())
    heap_offset = table_offset + int(header.get('THEAP', table_size))
    heap = reader.read(heap_offset + start, stop - start)
    count = rows.stop - rows.start
    small = header.copy()
    small['NAXIS2'], small['ZNAXIS2'], small['PCOUNT'] = count, count, len(heap)
    small.remove('THEAP', ignore_missing=True)
    small.remove('CHECKSUM', ignore_missing=True)
    small.remove('DATASUM', ignore_missing=True)
    rebased = descriptors.copy()
    rebased[:, 1] -= start
    body = rebased.astype('>i4').tobytes() + heap
    blob = EMPTY_PRIMARY + small.tostring().encode('ascii') + body + b'\0' * (-len(body) % BLOCK)
    with fits.HDUList.fromstring(blob) as hdul:
        return np.asarray(hdul[1].data)[:, columns]


def read_plane(reader, offset, name, rows, columns, guess=HEADER_GUESS):
    """Window of the named 2D plane whose HDU starts at `offset`; also returns the next HDU offset."""
    header, header_len, after = read_header(reader, offset, guess)
    if str(header.get('EXTNAME', '')).strip().upper() != name:
        raise RemoteError(f'Expected the {name} extension.')
    following = offset + header_len + padded(data_bytes(header))
    if header.get('ZIMAGE'):
        return read_compressed_rows(reader, offset, header, header_len, after, rows, columns), following
    if header.get('XTENSION', '').strip() != 'IMAGE' or header.get('NAXIS') != 2:
        raise RemoteError(f'The {name} extension is not a two-dimensional image.')
    return read_rows(reader, offset + header_len, header, rows, columns), following


def read_wave_table(reader):
    """The WCS-WAVE lookup table, the last HDU of every Level 2 product (two FITS blocks)."""
    for blocks in (2, 8):  # Two blocks in every release seen so far; look further back before failing.
        tail = reader.tail(blocks * BLOCK)
        for start in range(len(tail) - 2 * BLOCK, -1, -BLOCK):
            if tail[start:start + 20] == b"XTENSION= 'BINTABLE'":
                with fits.HDUList.fromstring(EMPTY_PRIMARY + tail[start:]) as hdul:
                    if len(hdul) == 2 and hdul[1].name == 'WCS-WAVE':
                        return hdul[1].copy()
    raise RemoteError('The WCS-WAVE wavelength table was not found at the end of the file.')


def measure_remote(session, uri, ra, dec):
    """Forced photometry of (ra, dec) in the remote exposure `uri`. Returns the measurement dict
    of `photometry.measure` plus wavelength, pixel position, header facts and bytes read."""
    reader = RangeReader(session, mirror_url(uri))
    primary, primary_len, after = read_header(reader, 0)
    image_offset = primary_len + padded(data_bytes(primary))
    header, header_len, _ = read_header(reader, image_offset, buffer=after)
    if (str(header.get('EXTNAME', '')).strip().upper() != 'IMAGE' or header.get('NAXIS') != 2
            or int(header.get('BITPIX', 0)) not in DTYPES):
        raise RemoteError('The first extension is not the SPHEREx IMAGE plane.')
    if str(header.get('BUNIT', '')).replace(' ', '') != 'MJy/sr':
        raise RemoteError('Unexpected surface-brightness unit.')
    width, height = int(header['NAXIS1']), int(header['NAXIS2'])
    facts = {'obs_id': header.get('OBSID'), 'detector': header.get('DETECTOR'),
             'mjd': header.get('MJD-AVG', header.get('MJD-OBS')), 'exposure_s': header.get('XPOSURE', header.get('EXPTIME')),
             'psf_fwhm_arcsec': header.get('PSF_FWHM')}
    x, y, area = locate(header, None, ra, dec)
    if not (np.isfinite([x, y]).all() and 0 <= x < width and 0 <= y < height):
        return {**facts, 'status': 'outside', 'bytes_read': reader.bytes_read}
    rows, columns = window(x, y, width, height)
    data_offset = image_offset + header_len
    image = read_rows(reader, data_offset, header, rows, columns)
    flags_offset = data_offset + padded(data_bytes(header))
    flags, variance_offset = read_plane(reader, flags_offset, 'FLAGS', rows, columns, 6 * BLOCK)
    variance, _ = read_plane(reader, variance_offset, 'VARIANCE', rows, columns, 4 * BLOCK)
    result = measure(image, variance, flags, x - columns.start, y - rows.start, area)
    result.update(facts, x=x, y=y)
    if result['status'] == 'ok':
        wave = read_wave_table(reader)
        science = fits.ImageHDU(header=header.copy(), name='IMAGE')
        spectral = wavelength_at(science, fits.HDUList([fits.PrimaryHDU(), science, wave]), x, y)
        if spectral is None:
            result['status'] = 'no_wavelength'
        else:
            result.update(wavelength_um=spectral['wavelength_um'], bandwidth_um=spectral['bandwidth_um'])
    result['bytes_read'] = reader.bytes_read
    return result
