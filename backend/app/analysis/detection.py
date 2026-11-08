"""Conservative residual screening. No astrophysical classification or motion fitting.

Evidence must come from independently validated calibration/registration/response checks,
not from a client request or invented FITS keywords. Production currently has no such
validator, so it returns visual-only results. Synthetic tests supply controlled evidence.
"""
from dataclasses import dataclass
import numpy as np
from scipy.ndimage import binary_erosion, label


@dataclass(frozen=True)
class DetectionEvidence:
    units: str
    calibration_verified: bool = False
    spatial_spectral_response_verified: bool = False
    psf_verified: bool = False
    registration_verified: bool = False


def detect_changes(a, b, grid, validation, evidence=None, *, threshold=6., min_pixels=3):
    """Screen aligned surface-brightness arrays using empirical residual MAD.

    Returned component sums are surface-brightness sums, NOT integrated source flux.
    Empirical scores are not Gaussian sigma or false-alarm probabilities. Correlated
    resampling noise is not propagated; no candidate uncertainty is fabricated.
    """
    if not np.isfinite(threshold) or threshold < 5 or min_pixels < 2:
        raise ValueError('Use threshold >= 5 and min_pixels >= 2')
    reasons = [r.detail for r in validation.reasons if r.severity != 'info']
    if not validation.difference_allowed:
        reasons.append('The temporal/spatial/spectral comparison gate did not accept this pair.')
    for attr, detail in (
        ('calibration_verified', 'Physical units and photometric calibration are not independently verified.'),
        ('spatial_spectral_response_verified', 'Spectral response equivalence across the analysis region is unverified; target wavelength alone is insufficient.'),
        ('psf_verified', 'PSF equivalence or validated PSF matching is unavailable.'),
        ('registration_verified', 'WCS reprojection has not been independently checked against stationary reference sources.')):
        if evidence is None or not getattr(evidence, attr):
            reasons.append(detail)
    if evidence is None or evidence.units != 'MJy/sr':
        reasons.append('This screener supports verified surface brightness in MJy/sr only.')
    result = dict(status='unavailable', candidates=[], reasons=reasons,
                  observations=[a.frame.summary(), b.frame.summary()],
                  compatibility=validation.to_dict(),
                  processing={'registration': 'bilinear WCS reprojection to common ICRS TAN grid',
                              'normalization': 'median background offset only; no source rescaling',
                              'noise': 'empirical residual MAD; not calibrated significance'},
                  limitations=['No motion or source identity is inferred.',
                               'Component sums are not aperture photometry.',
                               'Correlated noise and systematic calibration errors are not propagated.'],
                  conclusion='The observations are insufficient for scientifically reliable automatic change detection.')
    if reasons:
        return result
    valid = binary_erosion(a.valid & b.valid & np.isfinite(a.data) & np.isfinite(b.data), iterations=3, border_value=0)
    if valid.sum() < 100:
        result['reasons'].append('Too few valid interior pixels after boundary/mask erosion.')
        return result
    raw = b.data - a.data
    offset = float(np.median(raw[valid]))
    residual = np.where(valid, raw - offset, np.nan)
    noise = float(1.4826 * np.median(np.abs(residual[valid])))
    if not np.isfinite(noise) or noise <= np.finfo(float).eps:
        result['reasons'].append('Empirical residual noise cannot be estimated reliably.')
        return result
    candidates = []
    for sign in (1, -1):
        components, count = label(valid & (sign * residual >= threshold * noise))
        for idx in range(1, count + 1):
            yy, xx = np.nonzero(components == idx)
            if len(xx) < min_pixels:
                continue
            weights = np.abs(residual[yy, xx])
            x, y = float(np.average(xx, weights=weights)), float(np.average(yy, weights=weights))
            sky = grid.wcs.pixel_to_world(x, y)
            candidates.append(dict(id=f'C{len(candidates)+1}', x=x, y=y,
                ra=float(sky.ra.deg), dec=float(sky.dec.deg), pixels=len(xx),
                residual_sum=float(residual[yy, xx].sum()), units='MJy/sr pixel-sum',
                peak_residual=float(residual[yy, xx][np.argmax(weights)]),
                empirical_score=float(weights.max()/noise), uncertainty=None,
                positional_uncertainty_arcsec=None,
                interpretation='Positive residual candidate' if sign > 0 else 'Negative residual candidate',
                quality_flags=['empirical_noise_only', 'requires_independent_followup']))
            if len(candidates) >= 100:
                break
        if len(candidates) >= 100:
            break
    result.update(status='screened', candidates=candidates,
                  statistics=dict(background_offset=offset, empirical_noise=noise,
                                  valid_pixels=int(valid.sum()), threshold=threshold, candidate_limit=100),
                  conclusion=(f'{len(candidates)} residual candidates meet the empirical screening criteria; '
                              'additional observations and calibrated source measurements are required.' if candidates else
                              'No candidate residual met the selected empirical screening criteria.'))
    return result
