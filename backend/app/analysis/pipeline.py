"""Run one comparison on two local FITS files and write its preview PNGs.

Runs inside the isolated FITS worker process (see fits_worker.py). No network access.
"""
from pathlib import Path
from dataclasses import replace
from astropy import units as u
from .real_assessment import assess_real_pair

import numpy as np
from PIL import Image

from ..fits_image import stretch_pixels
from ..image_download import ImageError
from .compare import (
    FrameError, Reason, align, common_grid, cutout_size_for_grid, difference, load_frame, overlap_fraction, validate,
)

PREVIEWS = {'a': 'a.png', 'b': 'b.png', 'difference': 'difference.png'}


def _save(rgba, path):
    # Grid row 0 is the southern edge; flip once so north is up in the top-down PNG raster.
    Image.fromarray(rgba[::-1]).save(path, format='PNG')


def _difference_pixels(data, valid, noise):
    """Diverging gray: 128 is no change, brighter is B > A, darker is B < A. Invalid pixels transparent."""
    values = np.abs(data[valid])
    limit = max(float(np.percentile(values, 99.5)) if values.size else 0.0, 3 * noise, 1e-12)
    gray = np.full(data.shape, 128, dtype=np.uint8)
    gray[valid] = np.round(128 + 127 * np.clip(data[valid] / limit, -1, 1)).astype(np.uint8)
    rgba = np.stack((gray, gray, gray, valid.astype(np.uint8) * 255), axis=-1)
    return rgba, {'method': 'linear', 'limit': limit, 'zero_gray': 128,
                  'meaning': 'Mid-gray is no change; lighter means brighter in B, darker means fainter in B.'}


def compare_files(path_a, path_b, ra, dec, size_deg, mode, out_dir, source_a='file', source_b='file',
                  match_scale=False):
    try:
        grid = common_grid(ra, dec, size_deg)
        cutout_deg = cutout_size_for_grid(size_deg)
        frames = [load_frame(path_a, ra, dec, cutout_deg, source=source_a),
                  load_frame(path_b, ra, dec, cutout_deg, source=source_b)]
    except FrameError as exc:
        raise ImageError(str(exc), 422, exc.code) from exc
    except ValueError as exc:
        raise ImageError(str(exc), 422, 'invalid_compare') from exc
    a, b = align(frames, grid)
    overlap = overlap_fraction(a, b)
    check = validate(a.frame, b.frame, mode, overlap=overlap)
    if check.difference_allowed:
        try:
            units_ok=all(u.Unit(f.diagnostics.get('physical_unit','')) == u.MJy/u.sr for f in frames)
        except ValueError:
            units_ok=False
        if not units_ok:
            check=replace(check, decision='REJECT', difference_allowed=False,
                          reasons=check.reasons+(Reason('incompatible_units','reject','A meaningful subtraction requires both images in MJy/sr.'),))
    out = Path(out_dir)

    # One shared scale only when the pair may be compared directly; otherwise each frame gets
    # its own scale so wavelength-driven brightness is not presented as a change.
    shared = check.difference_allowed
    limits = None
    if shared:
        pooled = np.concatenate([a.data[a.valid], b.data[b.valid]])
        limits = tuple(float(v) for v in np.percentile(pooled, [1, 99]))
    scalings = {}
    for role, item in (('a', a), ('b', b)):
        if not item.valid.any():
            raise ImageError(f'Image {role.upper()} has no valid pixels on the comparison grid.', 422, 'no_valid_pixels')
        rgba, scalings[role] = stretch_pixels(item.data, ~item.valid, limits=limits)
        _save(rgba, out / PREVIEWS[role])

    diff_summary = None
    if check.difference_allowed:
        result = difference(a, b, check, match_scale=match_scale)
        rgba, display = _difference_pixels(result.data, result.valid, result.robust_noise)
        _save(rgba, out / PREVIEWS['difference'])
        diff_summary = {**result.diagnostics(), 'display': display}

    return {'context': 'real_observation_comparison', 'decision': check.decision, 'validation': check.to_dict(),
            'frames': [dict(frame.summary(), role=role) for role, frame in (('a', a.frame), ('b', b.frame))],
            'grid': grid.summary(), 'cutout_deg_used': cutout_deg, 'overlap_fraction': overlap,
            'stretch': {'method': 'asinh', 'percentiles': [1, 99], 'shared': shared,
                        'a': scalings['a'], 'b': scalings['b']},
            'difference': diff_summary,
            'detection': assess_real_pair(a, b, grid, check),
            'previews': {role: name for role, name in PREVIEWS.items()
                         if role != 'difference' or diff_summary is not None}}
