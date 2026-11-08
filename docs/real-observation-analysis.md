# Independent real-observation analysis

Branch feature/real-observation-analysis, based on main ae5c547. No merge/push.

## Implemented behavior

Normal comparison always assesses original FITS arrays on the existing common celestial grid.
It now records pipeline versions, physical units, variance positivity/median/units, PSF cube
shape, availability of calibrated spectral maps and five local approximate wavelength samples.
The assessment returns actual observation IDs/dates, time separation, overlap, structured
scientific checks and a plain-language conclusion. Detailed methods are expandable.

No real-data evidence flags are fabricated. Automatic candidate extraction remains unavailable
because this implementation does not validate field-wide spectral response, PSF matching,
independent source registration or relative photometric calibration. Existing temporal visual
subtractions remain explicitly exploratory. Candidate rendering is wired to real-context,
screened results only; no real candidates have been established. The existing detector is reused.
Diagonal variance is propagated using squared bilinear interpolation weights when units are valid. Covariance, background-fit uncertainty and calibration errors remain unmodeled; no calibrated significance or flux uncertainty is returned.

The slider offers an on-demand comparison with an earlier observation having the same
detector/collection/release, at least one hour separation, and no known large target-wavelength mismatch.
Known close target wavelengths rank ahead of unknown wavelengths, with closest time breaking ties. This is a preliminary shortlist, never proof of compatibility. The same ComparePanel performs
server assessment; no expensive analysis runs on frame movement. Results are retained for up to
six pairs and can be reopened; target and pair keys prevent displaying stale results as current.
Existing backend comparison cache and isolated FITS worker remain in use. Requests are aborted
when their comparison card unmounts; server processing remains bounded rather than forcibly killed.

Demo assets are REAL observations, not injected test images. An allowlisted demo_image_id input
resolves through the validated manifest, checks original FITS checksum and copies it into the
existing comparison worker. No arbitrary local paths or URLs are accepted on this path.
The same scientific gate applies to local and archive inputs. No new image service is introduced.

Scientific Detection Lab is hidden by default. Developers may explicitly start Vite with
VITE_ENABLE_DETECTION_LAB=true; its browser tests require that same explicit environment flag.
No injection routine is called by normal comparison or the slider.

## Independent observations actually executed

Seven same-detector pairs were assessed with 0.1-degree common grids from unchanged local assets.
All are QR2 source URLs. Original UTC timestamps:

- M101 A: 2026W21_2A_0213_2, 2026-05-22T19:40:19.088, D5, 4.366409 um.
- M101 B: 2026W21_2A_0213_3, 2026-05-22T19:42:28.021, D5, 4.403727 um.
- M31 A: 2025W28_1B_0480_4, 2025-07-09T14:56:47.965.
- M31 B: 2026W01_1A_0471_1, 2025-12-31T06:00:22.121.
- M31 C: 2026W28_2A_0117_1, 2026-07-10T00:02:31.613.

| Pair | Detector | Target wavelengths um | Separation h | Valid overlap | Visual subtraction |
|---|---|---|---|---|---|
| M101 A/B | D5 | 4.366409 / 4.403727 | 0.035815 | 97.56% | blocked |
| M31 A/B | D1 | 0.750227 / 0.894571 | 4191.059488 | 99.28% | blocked |
| M31 A/C | D1 | 0.750227 / 0.893465 | 8769.095458 | 99.31% | blocked |
| M31 A/B | D4 | 2.441900 / 2.979926 | 4191.059488 | 95.98% | blocked |
| M31 A/C | D4 | 2.441900 / 2.975124 | 8769.095458 | 95.60% | blocked |
| M31 B/C | D1 | 0.894571 / 0.893465 | 4578.035970 | 98.59% | available, exploratory |
| M31 B/C | D4 | 2.979926 / 2.975124 | 4578.035970 | 94.34% | available, exploratory |

M31 pipeline versions A/B/C: 6.4+psffix1 / 6.5.4+psffix1 / 6.5.7.
All local files contain FLAGS, VARIANCE and a 121x101x101 PSF cube; none includes CWAVE/CBAND.
Matching target wavelength is NOT full spectral equivalence. PSF cubes are not proof of matched
resolution. All seven scientific detection results were unavailable with zero candidates returned;
this is insufficient evidence, not a claim that no astrophysical changes occurred.

One bounded live IRSA metadata query for M31 D1 returned status live, 57 observations, untruncated.
The first result was 2026W32_1A_0420_1 at 2026-08-04T23:57:57.139 from QR3; later QR2 rows were also
present. Broad metadata wavelength bounds cannot certify spectral response or cross-release
calibration. No additional cutouts or calibration products were downloaded.

Reproduce the seven offline attempts:
`.venv/bin/python scripts/smoke_real_comparison.py`
It checks source checksums, uses temporary derived PNGs and prints measured JSON reports.

## Official scientific basis and remaining work

IRSA states WCS-WAVE is intended for visualization; science analysis needs CWAVE/CBAND from
Spectral WCS calibration products. See:
https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/
The spectrophotometry workflow also uses spatial PSFs, variance and a solid-angle calibration:
https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/sp.html

Before enabling actual detection: acquire/validate the relevant calibrated response products,
map them through detector/cutout coordinates, establish a response-equivalence policy, validate
PSFs and registration using stationary references, propagate variance/correlation through
resampling/matching, and validate source photometry on independent epochs. Extended-galaxy
residuals particularly require care. No motion inference or source classification is implemented.

## Actual verification

- Full backend suite: 230 passed, one existing Starlette/httpx deprecation warning (53.20 s).
- Final focused real-file/comparison API suite after provenance-label adjustment: 17 passed.
- Frontend unit suite: nine test files passed, zero failed/skipped.
- Production build: passed, existing large Aladin chunk warning.
- Normal browser suite: 39 passed, four skipped (two opt-in live FITS downloads and two
  developer-only lab cases); live IRSA search browser test excluded. Offline epoch comparison,
  cache reuse, eligibility UI, existing map/viewer/slider/playback/demo/filters all passed.
- All nine original FITS checksums match both manifests and initial main ae5c547 bytes.
- Real-data smoke: seven independent same-detector pairs completed. Two exploratory visual
  differences available; all scientific detection results blocked. No real candidates claimed.
- Live metadata query succeeded; no live FITS download or new calibration acquisition verified.

Status: REAL-OBSERVATION COMPARISON WORKING, DETECTION NOT VALIDATED.
- Explicit developer-flag lab browser run: two passed (3.8 s), confirming the old lab remains
  available for engineering use while absent from the normal product workflow.

Exploratory B/C residual measurements (MJy/sr): D1 median offset removed 0.050299,
residual MAD scale 0.471603 over 3432 valid common-grid pixels; D4 offset 0.018521,
MAD scale 0.268555 over 3284 pixels. Full-file native VARIANCE medians were D1 0.00254835 /
0.00269851 and D4 0.00144191 / 0.00147136 (MJy/sr)^2. These full-file medians describe a different sampling region from the common-grid cutout. The final pipeline also reports diagonal bilinear-propagated variance, but no calibrated residual significance is inferred.
Large structured galaxy residuals may reflect PSF, registration, spectral or calibration effects;
they were not extracted or labeled as astrophysical candidates.
