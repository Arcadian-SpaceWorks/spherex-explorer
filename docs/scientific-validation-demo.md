# Scientific Detection Lab

This is synthetic injection software validation, not evidence of astrophysical variability.
Production real-observation detection remains gated. The lab is available below the existing
comparison area in both Live and Demo modes; use `/?mode=demo` for network-independent use.

## Reproduction and provenance

Run the usual backend/frontend launcher, open Demo Mode, scroll to Scientific Detection Lab,
and choose Brightness Change, Synthetic Transient or No Change. No archive requests are made.
The API `/api/validation?experiment=transient&seed=0` accepts three named experiments and seeds
0–4 only. Results are computed locally and memoized (15 entries); the UI reports cache reuse.
To reproduce all metrics: `.venv/bin/python scripts/validate_detection_demo.py` from repo root.
The script prints JSON lines; redirect to a chosen derived report file if desired.

Background: bundled M31 observation `2025W28_1B_0480_4`, detector D1,
2025-07-09T14:56:47.965 UTC. The manifest `frontend/public/demo/manifest.json` provides
original IRSA source URL, FITS SHA-256 and provenance. Each experiment verifies that checksum,
loads a 0.17-degree native-WCS cutout with existing FITS utilities and preserves FLAGS/NaN
masks. No FITS files are written. The API reports original identity, date, path and hash.
No artificial second observation date or time separation is assigned.

## Experimental design

Reference and test share the same observed background, WCS, masks and MJy/sr units. Independent
seeded Gaussian noise is added to each copy. Its sigma is max(0.02 * background IQR, 0.01) MJy/sr:
a controlled perturbation, not a calibrated estimate of SPHEREx detector noise or use of the
VARIANCE extension. Maximum clearance from eroded masks selects the injection center.
The model is a circular Gaussian with sigma 1.5 pixels, explicitly not the archive PSF.

Brightness adds a synthetic baseline source of peak 50 noise units to both arrays, then adds
25 noise units to the test image. Transient adds only the 25-unit source to the test. No Change
adds noise only. Both positive experiments have identical residuals by construction; brightness
is not a test of real-source identification or deblending. The reference display includes
controlled noise (and the synthetic baseline for Brightness), and is labeled accordingly.

The existing detector removes a median offset, erodes overlap masks by three pixels, estimates
residual noise as 1.4826 times MAD, and extracts signed four-connected regions at threshold 6
with at least three pixels. Candidates have weighted centroids and native-WCS ICRS coordinates.
The peak residual is a surface-brightness measurement, not integrated source flux. It has no
calibrated uncertainty; its noise ratio is empirical, not Gaussian sigma or false-alarm probability.
Arrays share percentile/asinh display limits. Difference has a signed linear grayscale. PNGs
are vertically flipped; overlays use x+0.5 and height-y-0.5 to map pixel centers correctly.

Independent-observation eligibility is not changed. Controlled validation explicitly uses the
same background and known synthetic response/PSF/grid; it reports `synthetic_injection_validation`.
Normal comparison reports `real_observation_comparison` and never receives controlled evidence.

## Actual execution (2026-11-08)

Seeds 0–4: 5/5 brightness and 5/5 transient signals recovered with exactly one candidate each.
Localization error range 0.07647–0.20231 pixels. Injected peak change 2.886994 MJy/sr; peak errors
range -0.402866 to +0.231527 MJy/sr. Seed 0 recovered 3.095832 MJy/sr, error 0.208838, centroid
error 0.076475 pixel. Five No Change runs each produced zero candidates. This small experiment
does not establish a general false-positive rate. Threshold 5 also detects the seed-0 signal;
threshold 100 misses it and reports failed criteria, rather than concealing the miss.

Acceptance tolerance: centroid <0.6 pixel (subpixel recovery of a well-sampled sigma-1.5 Gaussian)
and peak error <5 injected noise sigmas (explicit engineering tolerance, not a confidence interval).
The API returns success/failure, measured values and explanations without inventing uncertainties.

Initial relevant backend run: 72 passed, one Starlette/httpx deprecation warning. Frontend unit
suite: eight files passed. Build passed, with existing Aladin large-bundle warning. Focused
Playwright lab/comparison/demo suite: 15 passed (15.5 s), including lab with external network
blocked. Screenshots: frontend/test-results/scientific-validation-transient.png and
frontend/test-results/scientific-validation-no-change.png (generated, ignored artifacts).
A final mask-clearance regression and cache-label check were added after that run; see final
engineering report for subsequent validation.

## Limits and next steps

This demonstrates controlled residual extraction/localization on realistic fixed galaxy texture.
It does not demonstrate real transient discovery, physical flux variability, motion, survey
completeness, or calibrated significance. No archive PSF interpretation, variance propagation,
correlated noise modeling, independent-epoch registration validation, spatial LVF compatibility
or calibration validation is supplied. Those remain prerequisites for real-observation detection.
The lab fixes one background/one injection location; multi-position completeness, crowding,
negative changes, non-Gaussian noise and detector artifacts require further work.

Final checks: lab backend suite 19 passed (1.46 s), including API isolation and mask clearance.
Final lab browser suite 2 passed (3.8 s), including explicit API error handling. Final production
build passed. All nine bundled original FITS checksums matched the manifest after execution.
