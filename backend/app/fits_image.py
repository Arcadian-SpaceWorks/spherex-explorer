"""SPHEREx IMAGE rendering and WCS readouts. Original FITS bytes stay untouched."""
import math
import re
import warnings

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS
from astropy.wcs.utils import skycoord_to_pixel, pixel_to_skycoord
from PIL import Image

from .image_download import ImageError

# Documented unusable pixel flags: NONFUNC, DICHROIC, MISSING_DATA.
BAD_FLAGS = (1 << 6) | (1 << 7) | (1 << 9)


def finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def science_hdu(hdul, max_pixels):
    matches = [(i, hdu) for i, hdu in enumerate(hdul) if hdu.name.upper() == 'IMAGE']
    if len(matches) != 1 or not isinstance(matches[0][1], (fits.ImageHDU, fits.CompImageHDU)):
        raise ImageError('Expected one SPHEREx IMAGE science extension; no primary-HDU fallback was used.', 422, 'unsupported_fits')
    index, hdu = matches[0]
    shape = hdu.shape
    if shape is None or len(shape) != 2 or min(shape) <= 0:
        raise ImageError('The IMAGE extension is not a two-dimensional science image.', 422, 'unsupported_fits')
    if math.prod(shape) > max_pixels:
        raise ImageError('The science image exceeds the configured pixel limit.', 413, 'image_too_large')
    return index, hdu


def wcs_header(header, key=' '):
    # Do not ask WCSLIB to parse unrelated alternate systems. Keep the original header intact.
    copy = header.copy()
    alternate = re.compile(r'^(?:WCSAXES|WCSNAME|CTYPE\d+|CUNIT\d+|CRPIX\d+|CRVAL\d+|CDELT\d+|CNAME\d+|CROTA\d+|PC\d+_\d+|CD\d+_\d+|PV\d+_\d+|PS\d+_\d+|RADESYS|EQUINOX|LONPOLE|LATPOLE)([A-Z])$')
    for name in list(copy):
        match = alternate.match(name)
        if match and match[1] != key:
            del copy[name]
        elif key == 'W' and re.match(r'^(A|B|AP|BP)_(ORDER|\d+_\d+)$', name):
            del copy[name]  # Spatial SIP distortion must not affect detector wavelength.
    return copy


def celestial_wcs(hdu, hdul):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        wcs = WCS(wcs_header(hdu.header), fobj=hdul)
    if not wcs.has_celestial:
        raise ValueError('No celestial WCS')
    return wcs.celestial


def wavelength_at(hdu, hdul, x, y):
    # Official IRSA tutorial: key W + table HDUs; SIP belongs to spatial WCS only.
    if 'CTYPE1W' not in hdu.header or 'WCS-WAVE' not in hdul:
        return None
    # Preflight table references before calling native WCSLIB (malformed references
    # can abort some WCSLIB builds instead of raising a Python exception).
    for axis in (1, 2):
        if not str(hdu.header.get(f'CTYPE{axis}W', '')).endswith('-TAB'):
            return None
        table_name = hdu.header.get(f'PS{axis}_0W')
        if table_name != 'WCS-WAVE' or not isinstance(hdul[table_name], fits.BinTableHDU):
            return None
        for parameter in (1, 2):
            if hdu.header.get(f'PS{axis}_{parameter}W') not in hdul[table_name].columns.names:
                return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            spectral = WCS(wcs_header(hdu.header, 'W'), fobj=hdul, key='W')
        spectral.sip = None
        values = spectral.all_pix2world([[x, y]], 0)[0]
        units = spectral.wcs.cunit
        wavelength = (float(values[0]) * u.Unit(units[0])).to_value(u.um)
        bandwidth = (float(values[1]) * u.Unit(units[1])).to_value(u.um)
        if finite(wavelength) is None or finite(bandwidth) is None:
            return None
        return {'wavelength_um': float(wavelength), 'bandwidth_um': float(bandwidth),
                'source': 'WCS-WAVE / alternate WCS W', 'approximate': True}
    except Exception:
        return None


def pixel_info(hdu, hdul, x, y, include_value=False):
    result = {'x': float(x), 'y': float(y), 'ra': None, 'dec': None,
              'spectral': wavelength_at(hdu, hdul, x, y)}
    try:
        sky = pixel_to_skycoord(x, y, celestial_wcs(hdu, hdul), origin=0).icrs
        result.update(ra=finite(sky.ra.deg), dec=finite(sky.dec.deg))
    except Exception:
        pass
    if include_value:
        ix, iy = int(x), int(y)
        value = finite(hdu.data[iy, ix])
        flags = None
        if 'FLAGS' in hdul and hdul['FLAGS'].shape == hdu.shape:
            flags = int(hdul['FLAGS'].data[iy, ix])
        result.update(value=value, flags=flags, masked=value is None or bool((flags or 0) & BAD_FLAGS))
    return result


def target_info(path, ra, dec, max_pixels):
    if ra is None or dec is None:
        return None
    result = {'ra': ra, 'dec': dec, 'status': 'wcs_unavailable'}
    try:
        with fits.open(path, memmap=False) as hdul:
            _, hdu = science_hdu(hdul, max_pixels)
            x, y = skycoord_to_pixel(SkyCoord(ra, dec, unit='deg', frame='icrs'), celestial_wcs(hdu, hdul), origin=0)
            if not np.isfinite([x, y]).all():
                return result
            height, width = hdu.shape
            inside = -.5 <= x < width - .5 and -.5 <= y < height - .5
            result.update(status='inside' if inside else 'outside', x=float(x), y=float(y))
            if inside:
                result['spectral'] = wavelength_at(hdu, hdul, x, y)
    except Exception:
        pass
    return result


def stretch_pixels(data, invalid, limits=None):
    """Return RGBA display pixels (still in FITS row order), never modify input data.

    `limits` (low, high) lets several images share one brightness scale; by default each image
    uses its own 1st and 99th percentiles.
    """
    valid = ~invalid
    if not valid.any():
        raise ImageError('No valid science pixels remain after masking.', 422, 'no_valid_pixels')
    low, high = np.percentile(data[valid], [1, 99]) if limits is None else (float(limits[0]), float(limits[1]))
    gray = np.zeros(data.shape, dtype=np.uint8)
    if high > low:
        values = np.clip((data[valid].astype(np.float64) - low) / (high - low), 0, 1)
        gray[valid] = np.round(255 * np.arcsinh(values / .1) / np.arcsinh(10)).astype(np.uint8)
    else:
        gray[valid] = 128  # Constant image: visible neutral gray, no division by zero.
    rgba = np.stack((gray, gray, gray, valid.astype(np.uint8) * 255), axis=-1)
    return rgba, {'method': 'asinh', 'percentiles': [1, 99], 'low': float(low), 'high': float(high),
                  'asinh_a': .1, 'constant': bool(high == low), 'valid_pixels': int(valid.sum()),
                  'masked_pixels': int(invalid.sum()),
                  'mask_policy': 'Nonfinite pixels and FLAGS bits 6 (NONFUNC), 7 (DICHROIC), 9 (MISSING_DATA) are transparent. Other flags remain visible.'}


def render_fits(path, preview_path, max_pixels):
    try:
        with fits.open(path, memmap=False, lazy_load_hdus=False) as hdul:
            if len(hdul) > 64:
                raise ImageError('Too many HDUs for this image viewer.', 422, 'unsupported_fits')
            index, hdu = science_hdu(hdul, max_pixels)
            data = np.asanyarray(hdu.data)
            invalid = ~np.isfinite(data) | np.ma.getmaskarray(data)
            notes = []
            if 'FLAGS' in hdul:
                flags_hdu = hdul['FLAGS']
                if flags_hdu.shape == data.shape and np.issubdtype(flags_hdu.data.dtype, np.integer):
                    invalid |= (flags_hdu.data & BAD_FLAGS) != 0
                else:
                    notes.append('FLAGS could not be applied: incompatible dimensions or datatype.')
            else:
                notes.append('No FLAGS extension; only nonfinite/masked pixels were excluded.')
            rgba, scaling = stretch_pixels(data, invalid)
            height, width = data.shape
            ratio = min(1, 1024 / max(width, height))
            preview_size = (max(1, round(width * ratio)), max(1, round(height * ratio)))
            # FITS y grows upward. Reverse rows exactly once for the top-down PNG raster.
            display = Image.fromarray(rgba[::-1])
            if preview_size != display.size:
                display = display.resize(preview_size, Image.Resampling.NEAREST)
            display.save(preview_path, format='PNG')
            center = pixel_info(hdu, hdul, (width - 1) / 2, (height - 1) / 2)
            header = hdu.header
            def keyword(name):
                return header.get(name, hdul[0].header.get(name))
            observed = keyword('DATE-OBS')
            if not observed and finite(keyword('MJD-OBS')) is not None:
                observed = Time(float(keyword('MJD-OBS')), format='mjd', scale='utc').isot
            hdus = []
            for i, item in enumerate(hdul):
                shape = list(item.shape) if hasattr(item, 'shape') and item.shape is not None else None
                hdus.append({'index': i, 'name': item.name, 'type': type(item).__name__, 'shape': shape,
                             'columns': list(item.columns.names) if isinstance(item, fits.BinTableHDU) else None})
            return {'science_hdu': index, 'width': width, 'height': height,
                    'preview_width': preview_size[0], 'preview_height': preview_size[1],
                    'observation_id': keyword('OBSID'), 'detector': keyword('DETECTOR'),
                    'observed_at_utc': observed, 'unit': keyword('BUNIT'),
                    'scaling': scaling, 'hdus': hdus, 'notes': notes,
                    'orientation': 'Native detector orientation: x increases right, y increases up; not rotated to north-up. Pixel coordinates are zero-based.',
                    'spatial_wcs': 'available' if center['ra'] is not None else 'unavailable',
                    'center': center, 'spectral_wcs': 'available' if center['spectral'] else 'unavailable',
                    'wavelength_note': 'Wavelength varies across this image. WCS-WAVE readouts are approximate visualization values; calibrated CWAVE/CBAND products are needed for scientific wavelength analysis.',
                    'science_header': header.tostring(sep='\n', endcard=False, padding=False),
                    'wavelength_header': hdul['WCS-WAVE'].header.tostring(sep='\n', endcard=False, padding=False) if 'WCS-WAVE' in hdul else None}
    except ImageError:
        raise
    except Exception as exc:
        raise ImageError('This FITS product could not be interpreted safely as a SPHEREx science image.', 422, 'invalid_fits') from exc


def read_pixel(path, x, y, max_pixels):
    with fits.open(path, memmap=False) as hdul:
        _, hdu = science_hdu(hdul, max_pixels)
        height, width = hdu.shape
        if not (0 <= x < width and 0 <= y < height):
            raise ImageError('Pixel coordinates are outside the science image.', 422, 'invalid_pixel')
        return pixel_info(hdu, hdul, x, y, include_value=True)
