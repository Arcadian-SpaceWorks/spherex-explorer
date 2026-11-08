"""Bounded, offline controlled injections into one checksum-verified real background."""
import base64
import hashlib
import io
import json
from pathlib import Path
import numpy as np
from astropy import units as u
from astropy.io import fits
from scipy.ndimage import binary_erosion, distance_transform_edt
from PIL import Image
from .compare import load_frame, Grid, AlignedFrame, Validation
from .detection import DetectionEvidence, detect_changes
from ..fits_image import stretch_pixels

ROOT = Path(__file__).resolve().parents[3] / 'frontend/public'
CONTEXT = 'synthetic_injection_validation'


def png(data, valid, limits=None, difference=False):
    if difference:
        limit = max(float(np.nanmax(np.abs(data))), 1e-10)
        gray = np.uint8(np.clip(128 + 127*np.nan_to_num(data)/limit, 0, 255))
        rgba = np.stack([gray, gray, gray, valid.astype('uint8')*255], axis=-1)
    else:
        rgba, _ = stretch_pixels(data, ~valid, limits=limits)
    out = io.BytesIO()
    Image.fromarray(rgba[::-1]).save(out, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()


def run_experiment(experiment='transient', seed=0, threshold=6.):
    if experiment not in ('brightness', 'transient', 'no_change') or seed not in range(5):
        # Public API uses small enumerated seeds; no paths or downloads accepted.
        raise ValueError('Unknown experiment or seed (0..4 required)')
    manifest = json.loads((ROOT/'demo/manifest.json').read_text())
    target = next(t for t in manifest['targets'] if t['id'] == 'm31')
    obs = target['observations'][0]
    path = ROOT / obs['fits_path'].lstrip('/')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != obs['fits_sha256']:
        raise ValueError('Background FITS checksum mismatch')
    frame = load_frame(path, target['ra'], target['dec'], .17)
    if u.Unit(frame.diagnostics['physical_unit']) != u.MJy/u.sr:
        raise ValueError('Unsupported surface-brightness units')
    # load_frame retains native WCS; both copies use that exact grid, with no resampling.
    base = frame.data.copy()
    safe = binary_erosion(frame.valid, iterations=10, border_value=0)
    if safe.sum() < 100:
        raise ValueError('No safe injection region')
    # Maximum clearance to edges and bad pixels is deterministic and needs no source identity.
    y, x = np.unravel_index(np.argmax(distance_transform_edt(safe)), safe.shape)
    yy, xx = np.indices(base.shape)
    model = np.exp(-((xx-x)**2+(yy-y)**2)/(2*1.5**2))
    # Synthetic noise is explicitly controlled, not a claim about archive variance semantics.
    noise = max(float(np.nanpercentile(base[frame.valid], 75)-np.nanpercentile(base[frame.valid], 25))*.02, .01)
    rng = np.random.default_rng(seed)
    a = base + rng.normal(0, noise, base.shape)
    b = base + rng.normal(0, noise, base.shape)
    amplitude = 25 * noise if experiment != 'no_change' else 0.
    if experiment == 'brightness':
        # Controlled brightness change of a SYNTHETIC source, not an identified real source.
        a += 50*noise*model
        b += 50*noise*model
    b += amplitude*model
    grid = Grid(frame.wcs, base.shape, target['ra'], target['dec'], .17, 6.15)
    check = Validation('controlled_injection', 'ACCEPT', (), True, 0., None, 1.)
    result = detect_changes(AlignedFrame(frame,a,frame.valid), AlignedFrame(frame,b,frame.valid), grid,
                            check, DetectionEvidence('MJy/sr',True,True,True,True), threshold=threshold)
    result['context'] = CONTEXT
    result['processing']['registration'] = 'Identical native WCS and fixed background; no registration performed'
    result['processing']['eligibility'] = 'Controlled copies only; not evidence for independent observation compatibility'
    candidates = result['candidates']
    nearest = min(candidates, key=lambda c: np.hypot(c['x']-x,c['y']-y)) if candidates else None
    error = float(np.hypot(nearest['x']-x, nearest['y']-y)) if nearest and amplitude else None
    recovered = nearest['peak_residual'] if nearest and amplitude else None
    residual = b-a-result.get('statistics',{}).get('background_offset',0)
    limits = tuple(float(v) for v in np.nanpercentile(np.concatenate([a[frame.valid],b[frame.valid]]),[1,99]))
    sky = frame.wcs.pixel_to_world(float(x),float(y))
    success = (not candidates) if not amplitude else bool(error is not None and error < .6 and abs(recovered-amplitude) < 5*noise)
    explanation = (f'Controlled {experiment} experiment: {len(candidates)} residual candidates. '
                   + (f'Nearest candidate localization error {error:.4f} pixels; recovered peak {recovered:.6g} MJy/sr versus injected {amplitude:.6g} MJy/sr. ' if error is not None else 'No injected signal recovered. ' if amplitude else 'No source signal was added. ')
                   + 'This tests software localization on a fixed real background with synthetic noise, not independent epochs or a real astronomical discovery.')
    return dict(context=CONTEXT, experiment=experiment, seed=seed, success=success,
                background=dict(obs_id=frame.obs_id, observed_at_utc=frame.observed_at_utc,
                                sha256=digest, fits_path=obs['fits_path'], source_url=obs['source_url']),
                injection=dict(x=int(x), y=int(y), ra=float(sky.ra.deg), dec=float(sky.dec.deg),
                               amplitude=amplitude, units='MJy/sr', sigma_pixels=1.5,
                               model='Synthetic circular Gaussian; not the archive PSF', noise_sigma=noise),
                measurements=dict(recovered_peak=recovered, localization_error_pixels=error,
                                  amplitude_error=None if recovered is None else recovered-amplitude,
                                  false_candidates=len(candidates) if not amplitude else None),
                shape=list(base.shape), display='A and B share 1–99 percentile asinh limits; difference is signed linear, gray=zero. Native grid; vertical PNG flip only.',
                previews=dict(original=png(a,frame.valid,limits), modified=png(b,frame.valid,limits),
                              difference=png(residual,frame.valid,difference=True)),
                detection=result, explanation=explanation)
