"""Measured real-observation assessment. Does not certify missing calibration evidence."""
from astropy import units as u
import numpy as np
from .diagnostics import feature_registration
from .detection import detect_changes


def assess_real_pair(a, b, grid, check):
    result = detect_changes(a, b, grid, check) # No caller can supply validation-copy evidence.
    diagnostics = [f.frame.diagnostics for f in (a,b)]
    units_ok = False
    try:
        units_ok = all(u.Unit(d.get('physical_unit','')) == u.MJy/u.sr for d in diagnostics)
    except ValueError:
        pass
    checks = [dict(code='units', passed=units_ok,
                   explanation='Both images use surface brightness in MJy/sr.' if units_ok else 'Physical image units are missing or incompatible.'),
              dict(code='variance', passed=all(d.get('variance',{} ) and d['variance'].get('median') is not None for d in diagnostics),
                   explanation='Variance is propagated through bilinear resampling when usable; correlated noise and PSF matching remain unmodeled.'),
              dict(code='spectral_calibration', passed=False,
                   explanation='Calibrated per-pixel wavelength and response equivalence have not been established. WCS-WAVE values are approximate visualization metadata.'),
              dict(code='psf', passed=False,
                   explanation='PSF models are recorded, but spatially varying PSF matching has not been validated.'),
              dict(code='registration', passed=False,
                   explanation='The images were mapped to the same sky grid; stationary reference sources have not verified the alignment.'),
              dict(code='calibration', passed=False,
                   explanation='Matching units or pipeline versions do not establish matching photometric calibration.')]
    result.update(context='real_observation_comparison', category='Insufficient Data for Reliable Analysis',
                  checks=checks, metadata=diagnostics, time_separation_hours=check.time_separation_hours,
                  wavelength_delta_um=check.wavelength_delta_um,
                  grid=grid.summary(),
                  follow_up='Obtain calibrated spectral maps, validate local PSFs and stationary-source alignment, and propagate measurement uncertainties before testing variability.')
    if not units_ok:
        summary = 'The image brightness measurements have missing or incompatible units, so they cannot be subtracted reliably.'
    elif check.overlap_fraction is not None and check.overlap_fraction < .9:
        summary = 'Too little of the same sky area has usable data in both images for a reliable difference analysis.'
    elif check.time_separation_hours is None:
        summary = 'An observation date is unavailable, so a change over time cannot be established.'
    elif check.wavelength_delta_um is not None and check.wavelength_delta_um > .02:
        summary = 'These images measured different infrared wavelengths at this location. Their appearance can differ even when nothing changed in space.'
    else:
        summary = 'We compared two observations, but cannot reliably tell whether a brightness difference comes from space or from the instrument and image processing.'
    result['registration_diagnostics'] = feature_registration(a,b)
    if a.variance is not None and b.variance is not None:
        both=a.valid & b.valid & np.isfinite(a.variance) & np.isfinite(b.variance)
        summed=a.variance+b.variance
        result['variance_propagation']={'method':'sum of squared bilinear weights for each independent input; then A+B',
            'valid_pixels':int(both.sum()), 'median_difference_variance':float(np.median(summed[both])) if both.any() else None,
            'units':'(MJy/sr)^2', 'limitation':'Diagonal variance only; input/output covariance, background-fit error and calibration systematics are not modeled. Not used as calibrated significance.'}
    else:
        result['variance_propagation']={'method':'unavailable','limitation':'Missing or unsupported variance map units'}
    result['outcome'] = 'VISUAL DIFFERENCES ONLY' if check.difference_allowed else 'IMAGES CANNOT BE RELIABLY COMPARED'
    result['conclusion'] = summary + ' No astronomical change is established by this comparison.'
    return result
