# Demo targets and prediction-aware 3I/ATLAS analysis

Integration branch: integration/demo-targets-cv.
Original main: f8c2314b2fc910ad33bf06d13bcc43766c726d8e.
Demo branch: feature/demo-more-targets at 8865174 (merge base 969236b).
The branch merge was automatic, with no Git conflicts. Semantic integration preserved main's
Find Changes card, real-science gate, variance/PSF diagnostics, cache and temporal playback.
The unrelated discovery-missions branch was not merged. Original branches/worktrees are retained.

## Available real data

60 real SPHEREx FITS/PNG/metadata triplets: M101 3, M31 18, Barnard's Star 21, 3I/ATLAS 18.
All 60 FITS checksums and all bundle metadata/preview checksums validate. The 9 FITS originally
on main remain byte-identical. Existing metadata was augmented by the demo branch; original
science arrays were not overwritten or altered. No additional astronomical images were downloaded.

The comet set contains 12 D5 and 6 D2 frames on 14 December 2025. It spans 12 exposure IDs but
13 exact UTC timestamps: D2 and D5 of 2025W50_2A_0698_1 differ by 1 ms. We preserve both times.
The baseline is 04:26:46.211 to 07:46:24.496 UTC, 3.327301389 hours. No local August or cross-month
comet images were available. All comet images are QR2, l2b-v20-2025-349, pipeline 6.4+psffix1.
They include real science, FLAGS, VARIANCE, PSF, ZODI and WCS-WAVE; CWAVE/CBAND are absent.

Authoritative collection:
https://irsawebops2.ipac.caltech.edu/data/SPHEREx/docs/comet3iatlas/index.html
That host timed out during inspection. Its canonical IRSA counterpart was accessible:
https://irsa.ipac.caltech.edu/data/SPHEREx/docs/comet3iatlas/index.html
A bounded retrieval of the official observation VOTable (276887 bytes) matched the bundled
SHA-256 11ff6a524c1b344b3c15c4875429b5b89fd053a18eef4d66328a5632382ef4af exactly.
Runtime checks match each observation ID, detector, UTC time and predicted coordinates to this
verified local table. The collection describes low signal-to-noise at many wavelengths and
extended comet emission. Published activity findings are external context, not reproduced results.

## Existing UI and processing

Demo Mode now supports A/B selection for all real preloaded targets. It uses the same comparison
API/service and isolated FITS worker as Live Mode. No second comparison service was introduced.
Per-target selection clears stale A/B picks, and changing targets cancels the previous export.

For 3I/ATLAS only, the existing slider and ComparePanel offer:

- Fixed sky: WCS reprojection to one north-up celestial grid, with predicted comet positions
  overlaid as dashed rings. This does not certify independent stationary-source registration.
- Follow predicted comet: each real image is reprojected around its own verified prediction.
  The comet prediction stays centered; stars move in the background. Same-sky subtraction and
  activity detection are disabled for these different celestial grids.

The existing cache keys include the view and verified ephemeris values. The slider prepares a
frame through a cached self-comparison; duplicate-epoch rejection still prevents interpreting it
as a change analysis. The cache, concurrency and 60-second worker limits remain enforced.
Comparison uses each selected frame's actual exposure prediction, never a single fixed comet RA/Dec.
Barnard's Gaia-propagated positions are explicitly distinguished from comet ephemerides, so its
normal playback is not accidentally sent through comet analysis. Fixed-sky native cutouts alone
are not labeled registered. Tracking video export is disabled; ordinary slider playback and
M31/M101/Barnard native WebM export remain available with their existing caveats.

## What is predicted versus measured

Official predictions span (167.2790891145°, 5.1215765783°) to (167.1259283847°, 5.1749508531°).
Astropy SkyCoord gives 581.799803 arcseconds separation and 174.856358 arcseconds/hour.
These numbers describe the ephemeris, NOT independent image-based comet motion. Spherical
geometry handles declination and RA wrapping; no physical speed or distance is inferred.

Each real file is also inspected near its own predicted position on its native grid. A radius-4
pixel search is compared with a robust radius-8–12 pixel annular background. Finite/FLAGS masks
are preserved. A peak contrast above five empirical background spreads permits reporting a
positive-weight local centroid within radius 3 of that peak, provided enough valid pixels exist.
A centroid offset over two native pixels is labeled ambiguous. This is a diagnostic search near
an ephemeris, not independent source identification or calibrated detection significance.

17 frames have unconfirmed local excesses; one has an ambiguous local excess (D5 exposure
2025W50_2A_0712_1, about 3.77 pixels from the prediction). All return source_identity_verified=false
and measured_comet_position=null. Consequently no measured comet displacement/rate is returned.
No frame is classified as an independently verified comet detection.

Examples: first D5 excess 0.942881 MJy/sr, offset 0.154 native pixels; last D5 excess
1.849830 MJy/sr, offset 0.540 pixels. These are local surface-brightness measurements without
calibrated source-flux errors. The approximate wavelengths differ (3.957515 / 4.351149 um), so
the values do NOT establish physical brightening. No PSF/aperture-corrected photometry, source
association, coma growth or calibrated activity variation has been validated. Different wavelengths
and background sources can change appearance. The real-observation science gate remains active.

Detailed per-frame measurements, original URLs, timestamps, checksums and diagnostics are in
comet-validation-results.json. Reproduce read-only with:
`.venv/bin/python scripts/validate_comet_demo.py`

## Validation record

Final test results and merge status are recorded after validation completes. Scientific limitations
remain regardless of test success: predicted motion, local image excesses, celestial reprojection
and real comet activity measurements are distinct levels of evidence.

## Exact comet frames

| Observation | UTC | Detector | Approx. wavelength at predicted comet (um) | Image check |
|---|---|---|---|---|
| 2025W50_2A_0685_1 | 2025-12-14T04:26:46.211Z | D2 | 1.216523 | unconfirmed_local_excess |
| 2025W50_2A_0685_1 | 2025-12-14T04:26:46.211Z | D5 | 3.957515 | unconfirmed_local_excess |
| 2025W50_2A_0685_2 | 2025-12-14T04:28:55.142Z | D5 | 3.992233 | unconfirmed_local_excess |
| 2025W50_2A_0685_3 | 2025-12-14T04:31:04.072Z | D2 | 1.275329 | unconfirmed_local_excess |
| 2025W50_2A_0685_3 | 2025-12-14T04:31:04.072Z | D5 | 4.027234 | unconfirmed_local_excess |
| 2025W50_2A_0685_4 | 2025-12-14T04:33:13.004Z | D5 | 4.062525 | unconfirmed_local_excess |
| 2025W50_2A_0698_1 | 2025-12-14T06:01:11.490Z | D5 | 4.097284 | unconfirmed_local_excess |
| 2025W50_2A_0698_1 | 2025-12-14T06:01:11.491Z | D2 | 1.336083 | unconfirmed_local_excess |
| 2025W50_2A_0698_2 | 2025-12-14T06:03:20.422Z | D5 | 4.133135 | unconfirmed_local_excess |
| 2025W50_2A_0698_3 | 2025-12-14T06:05:29.353Z | D5 | 4.169011 | unconfirmed_local_excess |
| 2025W50_2A_0698_4 | 2025-12-14T06:07:38.283Z | D2 | 1.434445 | unconfirmed_local_excess |
| 2025W50_2A_0698_4 | 2025-12-14T06:07:38.283Z | D5 | 4.205073 | unconfirmed_local_excess |
| 2025W50_2A_0712_1 | 2025-12-14T07:39:57.704Z | D5 | 4.240891 | ambiguous_local_excess |
| 2025W50_2A_0712_2 | 2025-12-14T07:42:06.635Z | D2 | 1.504265 | unconfirmed_local_excess |
| 2025W50_2A_0712_2 | 2025-12-14T07:42:06.635Z | D5 | 4.277466 | unconfirmed_local_excess |
| 2025W50_2A_0712_3 | 2025-12-14T07:44:15.566Z | D5 | 4.314252 | unconfirmed_local_excess |
| 2025W50_2A_0712_4 | 2025-12-14T07:46:24.496Z | D2 | 1.578306 | unconfirmed_local_excess |
| 2025W50_2A_0712_4 | 2025-12-14T07:46:24.496Z | D5 | 4.351149 | unconfirmed_local_excess |

## Executed checks

- Full backend suite: 249 passed, one existing Starlette/httpx TestClient deprecation warning.
- Final focused comet/M31 tests: 5 passed (geometry, actual predictions, both views, cache reuse,
  source-identity limits, altered ephemeris rejection and low-signal/NaN handling).
- Frontend unit suite: 9 test files passed. Production build passed with the existing large
  Aladin bundle warning.
- Stable complete relevant browser run: 43 passed, 4 skipped (2 live FITS opt-in downloads and
  2 developer-only lab cases); one live metadata search excluded. All 60 real frames browsed
  offline, both comet views exercised, existing comparison/viewer/filter/navigation paths,
  native M31 playback/WebM export and Demo/Live switching passed. No archive downloads allowed
  in offline tests.
- During implementation an initial M31 regression used obsolete inventory indices; it now selects
  the same intended observations explicitly by ID/detector. A comet epoch assertion was corrected
  to preserve the actual 13 timestamps/12 exposure IDs. Barnard's propagated Gaia positions were
  initially mistaken for comet ephemerides; comet routing now uses explicit target identity.
  A WebM export timed out while code was being edited; it passed in a stable focused run and
  again in the full run. No scientific gate was relaxed or failing test removed.
- Source assets: complete bundle validation passes; 60/60 current FITS hashes match manifests,
  9/9 original main FITS hashes match original main bytes. The official observation table was
  independently fetched with a 2 MiB cap and matches the bundled table exactly.

Screenshots (generated, ignored artifacts): frontend/test-results/comet-centered-comparison.png,
frontend/test-results/comet-tracking-playback.png. They show real FITS-derived previews with
predicted rings, not simulated data or verified source-centroid overlays.

Integration is intended to be committed with both main and demo branch ancestry intact. No push
or branch deletion. The final integration commit and post-main smoke results are reported in the
engineering handoff; no self-referential commit hash is embedded in this document.
- Explicit developer-flag lab browser suite: 2 passed (4.0 s), confirming it remains available
  for verification while hidden in the ordinary UI.
- FITS files are now explicitly marked binary in .gitattributes. This prevents meaningless text
  whitespace checks/text merges of science data and does not modify any FITS bytes.
