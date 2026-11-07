# Reviewed progress / wavelength integration

Base: `main` at `d1c2ff32fbd53e894fcaa843e08647019cb16a38` (clean checkout;
Demo Mode committed). Contributor found as remote-only
`origin/feature/image-progress-wavelength-filter` at
`bbcc8114b41eaa929173e5a6258d22e23574ce47`; no unprefixed branch exists.
Fetch succeeded. Merge base: `71b9b5af77335a8436ff4170271e6606092f8d9a`.
The contributor includes five commits: 15f66a1, af9aa74, d7a010e, 2a7442c,
bbcc811. Its merge-base diff changes 26 files, including pair suggestions and
image-center restrictions beyond the branch name's stated features.

Work is isolated on `integration/image-progress-wavelength-filter` in
`/tmp/skytracker-progress-integration`. Selective patch integration was chosen
because whole commits mix useful controls with duplicate older cutout code,
unsupported scientific comparison claims, and frontend code without Demo Mode.
No merge, history rewrite, main update, or push is part of delivery.

## Decision table

| Contributor files/change | Decision | Resolution |
| --- | --- | --- |
| README.md | ADAPT | Add current controls, limits and scientific semantics. Keep main's provenance/offline instructions; reject unmeasured fixed loading times and pair-comparison claims. |
| backend/app/image_download.py | ADAPT | Add configurable cutout cache count only. Retain main's numeric validation, parent-size handling, redirects and streamed bounds. |
| backend/app/image_service.py | ADAPT | Independent full/cutout retention; classify each entry once. Default three cutout entries, rather than thirty. Keep main's bounded queue, file lock, cache keys and FITS preservation. |
| backend/app/images.py | KEEP main | Cutout API is already present; no competing endpoint/service introduced. |
| backend/app/irsa.py | ADAPT | Whitelisted detector and product-wavelength queries before TOP/LIMIT; µm converted to ObsCore metres. Retain and flag null/inconsistent spectral bounds. Reject center-box filtering. |
| backend/app/main.py | ADAPT | Add optional observation query parameters; preserve demo router and existing clients without filters. Reject bulk pair endpoint. |
| backend/app/pairs.py | REJECT | Wavelength agreement alone does not establish spatial/PSF/photometric comparability. Cutout-center fallback is not target-pixel wavelength, and approximate WCS values cannot authorize scientific subtraction. Also starts multiple cutout preparations in one request. |
| backend/tests/test_api.py | ADAPT | Preserve main's suite; add filtered-query/metadata/units/precision regressions in test_observation_filters.py. |
| backend/tests/test_cutouts.py | KEEP/ADAPT | Preserve stronger main tests; add split-cache bounds/eviction regressions, adapted from the contributor's pair tests. |
| backend/tests/test_pairs.py | REJECT/ADAPT | Reject tests asserting ACCEPT/difference_allowed. Reuse the useful band-validation and cache-test ideas in focused tests. |
| frontend/src/App.jsx | ADAPT | Keep main's mode/target/abort flow. Share filter state across the active live or demo control, reset on mode/target changes, apply only deliberate filters. No extra image fetch path or confirmation dialogs. |
| frontend/src/components/CentreOffsetFilter.jsx | REJECT | Default 0.5° restriction excludes valid footprint/edge matches. Center distance cannot guarantee usable target pixels; post-query circular filtering also interacts with row limits. |
| frontend/src/components/CoordinatePanel.jsx | ADAPT | Add validated filter form and Enter submission while preserving coordinate selection. |
| frontend/src/components/DownloadProgress.jsx | ADAPT | Keep elapsed-time concept; use a monotonic clock and indeterminate progress. No estimated percentages, guessed backend stages or unsupported duration estimates. Stop waiting aborts the browser request, with accurate backend-work disclosure. |
| frontend/src/components/ImageInspector.jsx | ADAPT | Keep main's shared image adapter, local demo pixel URLs, metadata labels, full-image opt-in and timeout. Add elapsed wait, stop/retry and stale-response protection. Reject duplicated fetch/retry implementation and shortened timeout. |
| frontend/src/components/ObservationsTable.jsx | ADAPT | Display applied filter and unknown coverage without changing provenance, timestamps or detector labels. No center restriction or competing selection state. |
| frontend/src/components/TemporalImageExplorer.jsx | ADAPT | Reuse progress component for the existing selected-frame request; retain lazy cutouts and demo adapter. Reject the contributor's full-image wording and claim that moving the slider stops server downloads. |
| frontend/src/components/WavelengthFilter.jsx | ADAPT | Same control in both modes. Separate detector selection from actual spectral coverage; no hard-coded detector-range inference. |
| frontend/src/styles.css | ADAPT | Append scoped progress/filter styles with reduced-motion support; preserve demo/viewer/slider styling. |
| frontend/src/wavelengths.js | ADAPT | Keep input/query validation concepts; remove hard-coded detector wavelength mapping. Local demo coverage uses only supplied metre bounds, never approximate image-center wavelengths. |
| frontend/tests/browser/centre-offset.spec.js | REJECT | Tests a default exclusion that is intentionally absent. |
| frontend/tests/browser/images.spec.js | KEEP main / ADAPT ideas | Main tests retained. New image-progress.spec.js covers truthful elapsed state, stop/retry and stale responses, without confirmation-dialog coupling. |
| frontend/tests/browser/wavelength-filter.spec.js | ADAPT | Test live API parameters and offline demo filters, including retained unknown coverage and real UTC epochs. |
| frontend/tests/wavelengths.test.js | ADAPT | Check units, inclusive endpoints, invalid inputs, detector identity and real M101 unknown bounds; remove range lookup assertions. |
| scripts/smoke_cutout.py | KEEP main | Existing one-cutout transfer/time cap retained; no larger contributor smoke transfers. |
| scripts/smoke_pairs.py | REJECT | Bulk transfer workflow and unsupported comparison feature not included. |

## Scientific and architectural behavior

The optional API parameters are `band=SPHEREx-D1` through `SPHEREx-D6` and
`wavelength_um=0.7..5.1` (a supported input range, not a claim about detector
coverage). Existing unfiltered queries are unchanged. Wavelength selection uses
`em_min`/`em_max` in **metres** before the archive result limit. Null, nonpositive,
or reversed bounds are retained as unverified; the result reports their count.
No detector-wide range is substituted for unavailable metadata. Query literals
retain floating-point precision, and endpoints are inclusive. Truncated archive
results remain explicitly marked; this does not deliver an exhaustive survey.

This is whole-product spectral coverage, not proof of coverage at the selected
pixel. SPHEREx LVFs vary across each detector, and existing WCS-WAVE readouts are
approximate. The M101 bundle lacks product-level spectral bounds, so a numeric
wavelength filter retains all three unverified frames; a D5 detector filter selects
the two real D5 frames at their original UTC epochs. No URLs, dates, WCS values,
FITS science arrays or demo manifests/assets were altered.

Primary references:
- [IVOA ObsCore](https://www.ivoa.net/documents/ObsCore/20170509/REC-ObsCore-v1.1-20170509.pdf): spectral bounds expressed as wavelength in metres.
- [IRSA SPHEREx introduction](https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/): spatially varying wavelengths and approximate spectral WCS.
- [SPHEREx instrument](https://spherex.caltech.edu/page/instrument): linear variable filters and multiple detector positions per source.

Both modes use main's image adapter and existing viewer/slider. Progress is elapsed
waiting time, not network bytes, stage telemetry, or a latency guarantee. Stopping
the browser wait does not stop an active synchronous backend job; work can finish
and populate the cache. No new progress polling, background acquisition or image
service was added. Preview controls wait for actual PNG load.

Full files and cutouts retain separate count/TTL bounds, default three each.
`SKYTRACKER_FITS_CACHE_ENTRIES` controls full files;
`SKYTRACKER_CUTOUT_CACHE_ENTRIES` controls cutouts. At the default 128 MiB per-file
cap, six retained FITS files can occupy up to 768 MiB, plus previews/metadata and
one temporary preparation. Operators can lower counts/size limits. This change
retains main's serialized processing: ordinary slider/viewer overlap waits and
reuses results, while queue saturation/timeouts may still return viewer_busy.

The existing scientific warnings remain: independent display normalization,
different wavelengths and coverage, native orientation, no image registration,
and no validated source motion or brightness variability. Only M101 is prepared;
M31 remains explicitly missing. Demo playback works from local assets without
IRSA. Live IRSA filtering was exercised with mocks, not a new archive transfer.

## Validation and limits

- Backend: `PYTHONDONTWRITEBYTECODE=1 timeout 120 .venv/bin/python -B -m pytest -p no:cacheprovider backend/tests -q`.
  **134 passed** (30.21 s), one existing Starlette/httpx deprecation warning.
  Includes IRSA parsing/query construction, FITS/headers/WCS, cutouts, independent
  cache eviction/limits, demo preparation/readout and identical/concurrent image
  cache reuse. Execution outside the sandbox is required for FastAPI TestClient.
- Frontend: `npm test`; four test files pass.
- Production: `npm run build`; passes, with the existing large Aladin chunk warning.
- Browser: `SKYTRACKER_LIVE_FITS=0 npm run test:browser -- --grep-invert 'search button returns live IRSA metadata'`:
  **20 passed, 2 skipped** (18.6 s). One unmocked archive search test deliberately
  excluded; both opt-in live FITS tests skipped. Real Aladin map/click/navigation,
  mocked live search/filters, progress stop/retry, viewer controls/pixels/download,
  stale requests, UTC slider switching, offline real M101 playback and mode/target
  changes passed. No full-detector archive downloads were initiated.
- An initial browser run failed the existing map test because its mouse point was
  below the viewport after main's mode selector increased page height. The test now
  scrolls the map into view and refreshes bounds after form interactions; the real
  Aladin implementation was not changed. Subsequent bounded suite passes.
- An inclusive-boundary unit test caught floating-point error from multiplying
  by `1e-6`; conversion now divides by 1,000,000 consistently in backend/frontend.
  Final frontend unit tests pass.
- `scripts/prepare_demo.py --validate frontend/public/demo` passes: three M101
  frames across two epochs, M31 missing. No scientific binary asset changes.
- `git diff --check` passes. No dependencies added. No fresh IRSA dataset or cold
  archive performance measurement is claimed.

## Exact integrated files relative to main

```text
README.md
backend/app/image_download.py
backend/app/image_service.py
backend/app/irsa.py
backend/app/main.py
backend/tests/test_cutouts.py
backend/tests/test_observation_filters.py
docs/image-progress-wavelength-integration.md
frontend/src/App.jsx
frontend/src/components/CoordinatePanel.jsx
frontend/src/components/DownloadProgress.jsx
frontend/src/components/ImageInspector.jsx
frontend/src/components/ObservationsTable.jsx
frontend/src/components/TemporalImageExplorer.jsx
frontend/src/components/WavelengthFilter.jsx
frontend/src/styles.css
frontend/src/wavelengths.js
frontend/tests/browser/image-progress.spec.js
frontend/tests/browser/map.spec.js
frontend/tests/browser/wavelength-filter.spec.js
frontend/tests/wavelengths.test.js
```

Delivery is a validated integration commit only. With a clean main worktree, review
and fast-forward explicitly using:

```bash
git switch main
git merge --ff-only integration/image-progress-wavelength-filter
```

If main has advanced and fast-forward is refused, stop and rebase/merge the
integration branch with the newer main in isolation and rerun relevant checks;
do not reset main. No push is needed for local delivery.
