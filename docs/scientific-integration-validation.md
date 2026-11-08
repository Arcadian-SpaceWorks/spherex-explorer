# Scientific feature integration validation — 2026-11-08

Original local main: 969236be2ed40987b13e7e413c23c568daf93614.
Source: feature/scientific-validation-demo at 6a775bd6de7bf5cf8e1edbf7df296ebe381c041e.
Integration branch: integration/scientific-detection-main, isolated worktree
/tmp/skytracker-scientific-integration.

The source work was already committed and the working tree was clean when integration began.
Its single commit includes both scientific detection and the validation lab. The related
feature/scientific-change-detection ref remains at original main; it has no additional unique
commits. Main is the source commit's parent. Integration used a fast-forward, preserving all
history; no cherry-pick, conflict resolution or production implementation rewrite was needed.
Existing stale worktree registrations were left untouched. No dependencies were installed;
existing local dependencies were temporarily linked into the isolated worktree for testing.

Added integration regressions assert that an ACCEPTed visual comparison still has unavailable
automatic detection, no candidates, and explicit PSF/spectral reasons; API requests cannot
supply synthetic context or evidence; the UI displays scientific rejection while keeping visual
differences operational. Actual API regression uses synthetic FITS and the real cache/worker;
browser comparison regression uses mocked HTTP responses. Neither is live archive validation.

## Actual checks on the integration branch

- `.venv/bin/python -m pytest backend/tests -q`: 229 passed in 54.34 s; one existing
  Starlette/httpx TestClient deprecation warning.
- `npm --prefix frontend test`: 8 test files passed, zero failed/skipped.
- `npm --prefix frontend run build`: passed; existing large Aladin chunk warning.
- `SKYTRACKER_LIVE_FITS=0 npm --prefix frontend run test:browser -- --grep-invert 'search button returns live IRSA metadata'`:
  40 passed, 2 skipped (1.1 minutes). Live FITS checks intentionally disabled; one live IRSA
  metadata search excluded. These external archive checks are NOT VERIFIED by this integration.
- Real Aladin/WCS navigation and small DSS2 tiles passed; mocked observation retrieval,
  wavelength filtering, FITS inspector/cutouts/progress, slider/playback/WebM export, comparison,
  scientific rejection, all three lab experiments, candidate details/overlays, M101/M31 offline
  playback and Demo/Live switching passed. Offline tests block external/archive requests.
- Reproducible validation script: brightness 5/5 and transient 5/5 recovered, centroid errors
  0.0764747–0.2023112 px. No Change: zero candidates in each of five seeded experiments.
- All nine bundled original FITS SHA-256 values match BOTH manifest hashes and bytes retrieved
  from original main with git show. No original science assets or manifests changed.
- `git diff --check`: passed.

Production automatic detection remains unavailable without independent evidence for calibration,
field-wide spectral response equivalence, PSF matching and stationary-source registration.
The real API does not accept evidence flags or synthetic context. Only the isolated, fixed-input
validation path supplies controlled-copy evidence and labels results synthetic_injection_validation.
Normal comparisons return real_observation_comparison. No source motion/variability/discovery is
established. Empirical residual noise scores are not calibrated statistical significance.

Remaining limitations: independent-epoch scientific detection and live archive availability are
unverified; the lab uses a fixed real background, synthetic Gaussian PSF/noise and a small seed
sample. Integration does not broaden the scientific claims. See scientific-validation-demo.md
and scientific-change-detection.md for experiment assumptions and measurements.
