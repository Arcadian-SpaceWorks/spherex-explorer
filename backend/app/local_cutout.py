"""Cut a SPHEREx product locally exactly as IRSA's image server does.

IRSA's `?center=<ra>,<dec>&size=<deg>deg` cutout of a level-2 product keeps every HDU in order:
2D planes with the IMAGE shape (IMAGE, FLAGS, VARIANCE, ZODI) are sliced, and only NAXIS1/2,
CRPIX1/2 and the alternate CRPIXnA / CRPIXnW keywords change, by the slice offset. PSF and
WCS-WAVE are copied unchanged; a tile-compressed plane (QR3 FLAGS) is written uncompressed, as IRSA does. The box is, per axis, n = round(size / pixel scale of that axis)
pixels starting at ceil(centre - n/2) (zero-based, centre from the full SIP WCS), clipped to the
detector. Checked byte-for-byte against IRSA cutouts (see docs/live-mode-speed.md).
"""
import math
import warnings

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from .fits_image import wcs_header
from .image_download import ImageError

BLOCK = 2880
DTYPES = {8: 'u1', 16: '>i2', 32: '>i4', 64: '>i8', -32: '>f4', -64: '>f8'}
SHIFTED = ('', 'A', 'W')  # Primary, original-detector and wavelength-lookup pixel references.


def cutout_box(header, hdul, ra, dec, size_deg):
    """(x0, y0, width, height) in zero-based detector pixels, clipped; width/height may be 0."""
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        wcs = WCS(wcs_header(header), fobj=hdul).celestial
        xc, yc = (float(v) for v in wcs.all_world2pix([[ra, dec]], 0)[0])
    if not math.isfinite(xc) or not math.isfinite(yc):
        raise ImageError('The target has no position on this detector image.', 422, 'target_outside')
    matrix = wcs.pixel_scale_matrix
    sizes = (round(size_deg / math.hypot(matrix[0, 0], matrix[1, 0])),
             round(size_deg / math.hypot(matrix[0, 1], matrix[1, 1])))
    height, width = int(header['NAXIS2']), int(header['NAXIS1'])
    x0, y0 = math.ceil(xc - sizes[0] / 2), math.ceil(yc - sizes[1] / 2)
    x1, y1 = min(x0 + sizes[0], width), min(y0 + sizes[1], height)
    x0, y0 = max(x0, 0), max(y0, 0)
    return x0, y0, max(0, x1 - x0), max(0, y1 - y0)


def _padded(data):
    return data + b'\0' * (-len(data) % BLOCK)


def irsa_cutout(source, destination, ra, dec, size_deg, max_pixels):
    """Write the IRSA-equivalent cutout of `source` to `destination`; return the box."""
    with fits.open(source, memmap=True, lazy_load_hdus=False) as hdul:
        if len(hdul) > 64:
            raise ImageError('Too many HDUs for this image viewer.', 422, 'unsupported_fits')
        images = [hdu for hdu in hdul if hdu.name.upper() == 'IMAGE']
        if len(images) != 1 or images[0].header.get('NAXIS') != 2:
            raise ImageError('Expected one two-dimensional SPHEREx IMAGE extension.', 422, 'unsupported_fits')
        science = images[0].header
        shape = (int(science['NAXIS2']), int(science['NAXIS1']))
        if math.prod(shape) > max_pixels:
            raise ImageError('The science image exceeds the configured pixel limit.', 413, 'image_too_large')
        x0, y0, width, height = cutout_box(science, hdul, ra, dec, size_deg)
        if not width or not height:
            raise ImageError('The target is outside this detector image.', 422, 'target_outside')
        output = bytearray()
        with open(source, 'rb') as raw:
            for index, hdu in enumerate(hdul):
                info = hdul.fileinfo(index)
                header = hdu.header
                planar = (hdu.is_image and header.get('NAXIS') == 2 and header.get('BITPIX') in DTYPES
                          and (int(header['NAXIS2']), int(header['NAXIS1'])) == shape)
                if not planar:
                    raw.seek(info['hdrLoc'])  # Header and data copied verbatim, as IRSA does.
                    output += raw.read(info['datLoc'] - info['hdrLoc'] + info['datSpan'])
                    continue
                header = header.copy()
                header['NAXIS1'], header['NAXIS2'] = width, height
                for axis, offset in (('1', x0), ('2', y0)):
                    for key in SHIFTED:
                        name = f'CRPIX{axis}{key}'
                        if name in header:
                            header[name] = float(header[name]) - offset
                output += header.tostring().encode('ascii')
                dtype = DTYPES[header['BITPIX']]
                if isinstance(hdu, fits.CompImageHDU):
                    # QR3 stores FLAGS tile-compressed; IRSA writes the cutout as a plain image. Only the
                    # needed tiles are decompressed. Scaled compressed planes are left to IRSA.
                    if header.get('BSCALE', 1) != 1 or header.get('BZERO', 0) != 0:
                        raise ImageError('Scaled compressed planes are not cut locally.', 422, 'unsupported_fits')
                    cut = np.asarray(hdu.section[y0:y0 + height, x0:x0 + width]).astype(dtype, casting='same_kind')
                    output += _padded(np.ascontiguousarray(cut).tobytes())
                    continue
                plane = np.memmap(source, dtype=dtype, mode='r', offset=info['datLoc'], shape=shape)
                output += _padded(np.ascontiguousarray(plane[y0:y0 + height, x0:x0 + width]).tobytes())
                del plane
    with open(destination, 'wb') as handle:
        handle.write(output)
    return {'x0': x0, 'y0': y0, 'width': width, 'height': height}
