# Scientific change detection: engineering validation

Implemented on feature/scientific-change-detection from main 969236b.

## Initial audit

PASS: original science FITS input; bilinear WCS reprojection to a common north-up TAN grid;
finite/FLAGS masking; UTC DATE-OBS/MJD handling; target wavelength and overlap gate.
PARTIAL: spectral compatibility (target only), normalization (median offset or optional core
ratio), empirical residual MAD. FAIL: calibrated significance, PSF validation, independent
registration validation, source detection and scientific classification.
The old ACCEPT label meant a visual subtraction was allowed, not validated astrophysics.

## Implemented boundary

analysis/detection.py screens aligned science arrays only when independently validated
calibration, spatial spectral equivalence, PSF equivalence and reference-source registration
evidence are supplied by Python callers. No HTTP request can assert those facts. The current
production pipeline supplies none: automatic astrophysical detection is unavailable and
returns explicit reasons. Visual comparison remains available. The UI checks scientific
eligibility and explains the result. No production candidate overlays or source table are
exposed while scientific eligibility is unresolved.

For controlled experiments, screening erodes masks/boundaries by three pixels, subtracts a
median background offset and measures residual MAD. Positive and negative connected regions
above six empirical noise units with at least three pixels become residual candidates (max
100). Positions are weighted centroids converted through the common WCS. Component sums are
surface-brightness pixel sums, not integrated fluxes. No positional uncertainty, Gaussian
significance, motion matching, transient classification or calibrated flux uncertainty is
invented. No original FITS is modified. No PSF matching or variance propagation is implemented.
Independent evidence is essential: merely setting the evidence flags is not validation.

## Local real data inspection

All nine included M101/M31 FITS files were opened locally without network retrieval. They
contain IMAGE (MJy / sr), FLAGS, VARIANCE (MJy2 / sr2), ZODI, PSF and WCS-WAVE extensions.
WCS target coverage was valid in a 0.1 degree inspection cutout. Variance/PSF presence does
not validate their semantics, matching or propagation through interpolation.
M101 observations span about two minutes and different wavelengths; not suitable temporal
pairs. M31 D1 target wavelengths for July 2025 / December 2025 / July 2026 are approximately
0.75023 / 0.89457 / 0.89346 um; D4 approximately 2.44190 / 2.97993 / 2.97512 um.
Later same-detector pairs warrant further investigation, but field-wide LVF equivalence,
PSF consistency and calibration have not been established. No real astrophysical change
was detected or claimed. Extended galaxy subtraction needs special care.

## Engineering tolerances

Synthetic tests use a fixed random seed and known WCS, identical PSF and units. Centroid
recovery tolerance is 0.6 pixel; injected peak amplitude 25 is recovered within 4 surface
brightness units. Integer WCS translation aligns stationary peaks within one pixel. Moving
injections yield signed residuals only, with no motion measurement. No-change, background,
bad-pixel and noise-change cases require zero accepted residual components. Missing evidence
and incompatible spectra/overlap block screening. These are limited controlled experiments,
not a survey completeness or false-alarm calibration. Real-data variance propagation,
PSF modeling, field-wide response checks and source-reference registration validation remain
required before production automatic detection can be enabled.

## Actual validation results (2026-11-08)

- Full backend run: 206 passed, one Starlette/httpx deprecation warning (50.03 s).
  This run preceded the two final noise-change/PSF-saturation tests.
- Final focused detection + comparison run: 40 passed (1.97 s), including all 12 new
  detection tests and those two final artifact tests.
- Frontend Node suite: 8 test files passed, none failed or skipped.
- Production Vite build: passed; existing large Aladin bundle warning remains.
- Existing Playwright comparison suite: 8 passed (10.3 s). These mock image/observation
  HTTP responses; they are not live IRSA scientific validation. New unavailable-result
  panel was build-checked but has no dedicated browser assertion yet.
- Brightness injection centroid (44.9073, 50.0505) versus (45,50), peak 24.9410
  versus injected 25; empirical residual score 17.7745 (not calibrated sigma).
- Transient injection centroid (64.9205,60.0907) versus (65,60), peak 24.8144
  versus injected 25; empirical score 17.6354.
- No-change and bad-pixel cases: zero residual candidates over 8836 and 8792 valid
  interior pixels respectively, at threshold 6 and minimum component size 3.
- Moving source: one positive and one negative component; no displacement or angular
  rate inferred. This is not a demonstrated moving-object detector.
- No new archive downloads, no real-data change claims, no full live browser regression.

Verdict: PARTIALLY VALIDATED. Controlled residual screening is demonstrated; production
scientific eligibility validation and automatic astrophysical detection remain unavailable.
