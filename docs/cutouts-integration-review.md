# Cutout integration review

Reviewed branch: `feature/cutouts` at `15f66a10d3ec0f0c0e4ffc2140eaacebb1274bca`.
Base for integration: local/remote main at `71b9b5af77335a8436ff4170271e6606092f8d9a`.
Merge base: `6c7d280bde1914a339cd3f4ebd45dbfb004d8a1a`.

The original checkout was clean, including untracked files. Remote metadata was
fetched without changing source files. Work was isolated in
`/tmp/spherex-cutouts-reviewed`, branch `integrate/cutouts-reviewed`.
The separately published `origin/integrate/cutouts-main` was not incorporated;
this audit is limited to the requested feature and necessary fixes.

## File audit of feature/cutouts

| File | Decision | Reason / retained behavior |
| --- | --- | --- |
| README.md | MODIFY | Keep usage and API documentation; replace unsupported speed claims, explain clipping, shared cache limits and scientific limitations; link official documentation. |
| backend/app/image_download.py | MODIFY | Keep allowlisted DataLink-to-cutout pipeline. Validate before network access; bypass parent length rejection only for cutouts; retain actual stream limits; block redirects that lose cutout parameters. |
| backend/app/image_service.py | MODIFY | Keep distinct parameterized cache entries and cutout metadata. Validate before rounding. Preserve main's bounded queue and file lock behavior. |
| backend/app/images.py | KEEP | Optional bounded cutout size and coordinate-pair validation preserve existing full-image requests. |
| backend/tests/test_cutouts.py | MODIFY | Keep synthetic tests; add oversized-parent/stream limits, scientific byte/header/table preservation, invalid-pixel PNG behavior, input boundaries and redirect protection. |
| frontend/src/components/ImageInspector.jsx | MODIFY | Keep default cutout, explicit full mode and accurate download labels. Reject extra busy retries and shorter timeout; match Time Slider request size. |
| frontend/src/styles.css | KEEP | Add only mode-control styles, retaining main's Time Slider styles. |
| scripts/smoke_cutout.py | MODIFY | One small live cutout, 16 MiB response cap, 90-second download budget, temporary cache, diagnostic errors and cache/PNG verification. |

Selective patch integration was chosen because the feature commit predates main's
Time Slider and concurrency fixes. The stylesheet patch conflicted with appended
Time Slider styles; the mode rule was added without replacing those styles.
No source files were deleted and unrelated branch history was not rewritten.

## Necessary supporting changes

- `frontend/src/imageAdapter.js`: share the 0.3 degree request size with the inspector;
  otherwise the automatically loading slider would still download full images.
- `backend/tests/test_image_concurrency.py`: exercise both full and cutout requests
  with the retained queue; duplicate cutouts download once and reuse cached results.
- `frontend/tests/timeline.test.js`: check the updated optional request field.
- `frontend/tests/browser/images.spec.js`: verify matching slider/inspector requests,
  cutout labels and reversible explicit full mode.
- `frontend/tests/browser/live-image.spec.js`: update opt-in expectations for cutout
  dimensions rather than assuming a full 2040 by 2040 detector.

## Scientific and API review

The URL format is documented by IRSA:
https://irsa.ipac.caltech.edu/ibe/cutouts.html and
https://irsa.ipac.caltech.edu/data/SPHEREx/docs/cutout_tool.html.
Only HTTPS SPHEREx products on the existing exact host/path allowlist are used.
Every redirect is validated, and cutout requests cannot silently redirect to a
full product. Unsupported cutouts fail explicitly without full-image fallback.
Full requests retain the existing byte/pixel/time bounds and require an explicit
UI choice; existing API clients can still omit the optional field.

Downloaded MEF bytes are immutable. PNG stretching/masking does not modify FITS
values. Synthetic tests verify byte identity, checksum, WCS placement, spectral
lookup tables, IMAGE/FLAGS/VARIANCE/ZODI/PSF HDUs and transparent invalid pixels.
These tests validate preservation of the response, not an independent comparison
of IRSA's cutout extraction with the parent detector. No parent file was downloaded
for such a comparison. WCS-WAVE wavelengths remain approximate, as in main.

Cache keys distinguish access URL, rounded target and requested size from full
images. Entry count, TTL, bytes and pixel limits remain bounded. The same cache
capacity is shared by slider, inspector, full images and cutouts. A longer sequence
can evict old frames, requiring another bounded download. Queue saturation and
wait timeouts can still produce viewer_busy; normal overlapping requests wait and
reuse prepared results rather than failing immediately.

## Validation

- Backend: `python -m pytest backend/tests -q`: **86 passed**, one existing
  Starlette/httpx deprecation warning. Tests run outside the sandbox because
  FastAPI TestClient stalled inside it; the stalled sandbox run was interrupted.
- Frontend: `npm test`: **2 test files passed**, no failures.
- Production: `npm run build`: **passed**; Vite warns about the existing large
  Aladin bundle.
- Browser: `npm run test:browser`: **14 passed, 2 skipped**, 22.8 seconds.
  Covers real Aladin selection/navigation, live observation search through Vite,
  inspector pan/zoom/pixel/download, chronological switching, delayed-response
  protection, image failures/retries, mobile layout and cutout/full mode.
  The two opt-in live image tests were not run, avoiding multiple large transfers.
  Browser servers required execution outside the sandbox.
- `git diff --check`: passed.
- Live bounded smoke: first attempt failed to deliver the product. A retry
  succeeded: M31, observation `2026W32_2A_0201_1`, D3, QR3 product;
  0.02 degree request, 12 by 12 science pixels, 3943 KiB, 45.2 seconds;
  target inside WCS, center wavelength 1.743 micrometers.
  Final run after redirect protection: 49.2 seconds, same 3943 KiB / 12 by 12
  cutout; cached replay plus PNG check 0.34 seconds, same image ID, spatial and
  spectral WCS available, seven HDUs.
  No unrestricted full FITS transfer was initiated. A direct full-file speed or
  size comparison was intentionally not measured.

The live product's service time is variable. A small science array can still
include substantial ancillary HDUs, so bytes do not scale directly with the
science pixel count. This is not a guarantee of subsecond remote loading.
