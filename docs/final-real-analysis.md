# Final real-observation change analysis

Verdict: READY — REAL IMAGE COMPARISON WITH SCIENTIFIC LIMITATIONS.

## Scope and usability

Finalized on feature/real-observation-analysis, based on main ae5c547. The branch included
uncommitted work from the preceding real-observation pass, all preserved and reviewed here.

The existing comparison card has one primary action: Find Changes. Time comparisons request
chronological inputs. Before and After are labeled from actual FITS dates; aligned images and
signed differences are shown together when subtraction is meaningful. Brightness scales and
signed difference meaning are explicit. Missing dates, incompatible units, little overlap and
wavelength differences produce honest messages. Details are collapsed under “How did we reach
this conclusion?” and include provenance, IDs/dates, calibration, PSF, alignment and noise evidence.

The existing slider opens the same card via Compare with previous observation. Shortlisting
rejects known different archive releases and favors known close target wavelengths, then nearest
earlier time. It does not certify compatibility. Up to six analyzed pairs are retained in the
component; server comparisons use the existing bounded cache, with a bumped analysis-version key.
No processing is triggered on every slider movement. Unmounting aborts pending client requests;
changing mode also supersedes pending results. Server workers retain existing execution limits.
Candidate overlays are accessible by mouse/keyboard and reflect measured common-grid pixels;
only screened real-context results can display candidates. No actual real-data candidates were
established. Synthetic lab stays behind VITE_ENABLE_DETECTION_LAB=true and is absent by default.

## Scientific engineering improvements

- Bilinear reprojection of diagonal variance uses sum(w_i^2 * var_i), with positive finite
  variance, validated squared surface-brightness units, native masks and unsupported boundaries.
  A and B variances are added on their common valid grid. Input/output covariance, background-fit
  error, PSF convolution and calibration systematics remain unmodeled. No calibrated significance
  uses this partial variance model.
- Local PSF cube plane is selected using the documented CRPIXnA cutout-to-original transformation
  and PSF-zone headers. Signed empirical model moments, oversampling and negative absolute mass
  fraction are recorded. No negative-wing clipping or invented Gaussian PSF matching is applied.
  A model moment is not measured source sharpness or field-wide PSF equivalence.
- Up to 100 bright image peaks per frame are mutually matched within two common-grid pixels.
  Median shifts/RMS are diagnostics only: sources have no verified identity/stationarity, integer
  peak positions limit precision, and galaxy morphology/spectral/PSF effects can bias matching.
- A missing or incompatible physical unit now blocks even exploratory subtraction, while preserving
  side-by-side display. No automatic astrophysical detection gate was relaxed.

Official product documentation distinguishes WCS-WAVE visualization metadata from calibrated
CWAVE/CBAND science maps and describes PSF-plane selection for cutouts:
https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/
The calibrated maps are separate roughly 32 MB products per detector. None was present in the
local science files inspected; no calibration files were downloaded because this alone would not
resolve the independent registration and calibration validation requirements. No new dependencies.

## Actual real-data investigation

Ten pairs were executed: seven manifest-preserved same-detector M31/M101 pairs and three additional
M101 D2 pairs from existing checksum-verified cache files. Full evidence is in real-pair-results.json,
with exact source observation dates, target wavelengths, versions, checksums and measured diagnostics.
The ranking is for exploratory visual comparison (subtraction eligibility, then overlap), not a
confidence score or certified scientific ranking.

Best exploratory pairs:

| Region | Actual observations | UTC dates | Target wavelength um | Overlap |
|---|---|---|---|---|
| M31 D1 | 2026W01_1A_0471_1 / 2026W28_2A_0117_1 | 2025-12-31 06:00:22.121 / 2026-07-10 00:02:31.613 | 0.894571 / 0.893465 | 98.59% |
| M31 D4 | same IDs/dates | same dates | 2.979926 / 2.975124 | 94.34% |
| M101 D2 | 2025W19_2B_0346_1 / 2026W26_1A_0500_1 | 2025-05-10 17:04:37.741 / 2026-06-24 03:19:00.063 | 1.506419 / 1.489988 | 98.45% |

M31 elapsed time 4578.035970 hours (190.751499 days); the cached D2 pair spans 9826.239534 hours.
The other cached D2 observation is 2026W26_1A_0178_1 at 2026-06-22 20:21:33.190 UTC, target wavelength
1.420688 um. Its pairs fail the approximate temporal-visual wavelength gate. Earlier M31 epochs
also have large target-wavelength differences; the manifest M101 D5 pair is only about two minutes
apart. No alternative populated local target bundle was available.

For M31 D1, local model RMS widths are 0.499200 / 0.496045 native pixels; for D4, 0.623462 / 0.604815.
Both pairs yield one matched central image peak, with integer separation zero. This does NOT establish
subpixel registration accuracy or stationarity. Common-grid median diagonal difference variances
are 0.017991 (D1) and 0.011115 (D4) in (MJy/sr)^2 for the 0.1-degree analysis regions.
M101 images yield only three matched peaks; the cached comparison likewise remains unvalidated.

Three pairs allow exploratory visual subtraction. None permits scientific candidate extraction:
field-wide calibrated spectral-response equivalence and relative calibration remain unverified,
PSFs are not matched/validated, and reference sources/correlated noise are unresolved. Candidate
screening was NOT performed; empty candidate arrays do not mean that the sky was unchanged.
Structured galaxy/point-source residuals can be instrumental or processing effects and were not
classified as variable objects. No new FITS downloads or synthetic signals were used in these attempts.

Reproduce manifest pairs: `.venv/bin/python scripts/smoke_real_comparison.py`.
Include at most three cached M101 D2 images: add `--include-cache` (only when those local files exist).
The cache-only pairs are reproducible only on machines with the corresponding originals. Source
FITS are opened read-only; temporary derived previews are deleted with their temporary directories.

## Verification record

Final results are recorded below after checks complete. Backend tests use controlled fixtures for
algorithm tolerances, plus independent real FITS for API/gating/cache verification. Browser overlay
measurement tests use explicitly mocked screening results and are not real source detections.

- Final complete backend suite: 234 passed (52.49 s), one existing Starlette/httpx TestClient warning.
- Frontend unit suite: 9 test files passed, zero failures/skips. Production build passed with the
  existing large Aladin bundle warning.
- Full relevant browser suite: 40 passed, 4 skipped (two live FITS opt-in downloads, two developer
  lab tests); the live IRSA metadata browser test was excluded. Real Aladin navigation, mocked
  archive results, viewer/cutouts/progress, wavelength filters, slider/playback/export, M101/M31
  offline demos, Find Changes, real local epoch API/cache reuse, collapsed details and keyboard
  candidate overlays passed. Overlay positive-result tests are mocks, not observed candidates.
- An initial browser run failed one outdated message assertion; it was corrected to the new
  plain-English incompatibility message and the affected focused suite passed 11/11 before the
  successful full run. No science-gate test was removed.
- Final numerical diagnostics/real-file focused check: 5 passed, including incompatible units,
  native masks, known shifts, squared interpolation weights and signed PSF wings.
- All 9 original bundled FITS checksums match their manifests AND original main ae5c547 bytes.
  The 3 optional cached originals also matched their stored checksums before analysis. No FITS
  data were modified and no new FITS data were downloaded during finalization.
- Actual independent observations executed: 10 pairs, with 3 exploratory subtractions available;
  no scientifically eligible candidate screening. Live FITS retrieval remains NOT VERIFIED.

Example generated screenshot (ignored test artifact):
frontend/test-results/real-epoch-analysis.png.

## Changed files for delivery (relative to main ae5c547)

Backend: backend/app/analysis/compare.py, backend/app/analysis/diagnostics.py,
backend/app/analysis/pipeline.py, backend/app/analysis/real_assessment.py,
backend/app/compare_api.py, backend/app/compare_service.py.
Frontend: frontend/src/App.jsx, frontend/src/compareAdapter.js,
frontend/src/components/ComparePanel.jsx, frontend/src/components/TemporalImageExplorer.jsx,
frontend/src/styles.css.
Tests: backend/tests/test_processing_diagnostics.py, backend/tests/test_real_assessment.py,
frontend/tests/compare.test.js, frontend/tests/epochComparison.test.js,
frontend/tests/browser/compare.spec.js, frontend/tests/browser/epoch-analysis.spec.js,
frontend/tests/browser/validation-lab.spec.js.
Evidence/reproduction: scripts/smoke_real_comparison.py, docs/real-observation-analysis.md,
docs/real-pair-results.json, docs/final-real-analysis.md.

No merge or push. Reviewed changes are intended for a feature-branch commit; obtain its exact
hash from git log rather than embedding a self-referential hash here.
