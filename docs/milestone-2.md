# Milestone 2 verification and implementation notes

Verified 2026-11-06 on Fedora Linux, Python 3.14.8, Node 22.22.2 and installed headless Chrome. The existing React/Vite dashboard, Aladin Lite release and IRSA observations query were extended in place.

## Actual results

| Check | Result |
| --- | --- |
| `.venv/bin/python -m pytest backend/tests -q` | **57 passed**, including all 17 original tests |
| `npm --prefix frontend test` | Passed |
| `node frontend/tests/coordinates.test.js` | **2 passed** |
| `SKYTRACKER_LIVE_FITS=1 npm --prefix frontend run test:browser` | **7 passed**, including all 3 original browser tests |
| `npm --prefix frontend run build` | Passed |
| `bash -n scripts/setup.sh scripts/backend.sh scripts/frontend.sh` | Passed |
| Real DataLink resolution and bounded original FITS download | Passed, 71,637,120 bytes |
| Final isolated decoder on that original | Passed, spatial and spectral WCS available |

The final browser run used dedicated local ports 5174/8001 so it did not attach to the development servers on 5173/8000. The opt-in live image test reused the actual downloaded file in the local cache; it did not redownload 71 MB. It selected the observation through the live archive table, exercised `/api/images` and PNG delivery, clicked the rendered image, and received a real per-pixel WCS/wavelength readout. The other three new browser tests use explicit synthetic fixtures and mocked image responses to verify selection, pan/zoom, original-file download, loading/size-limit errors, retry, target changes, keyboard access and mobile layout.

The existing test warnings remain: Starlette's httpx TestClient deprecation and Vite's large Aladin chunk warning. No browser test coverage is claimed for Firefox or physical mobile hardware.

## Live file verified

The observation was obtained from the existing live TAP search at ICRS RA 210.80227°, Dec 54.34895°. Its metadata supplied the DataLink URL for observation **2026W26_1A_0500_1**, detector **D2**, collection **spherex_qr2**. The live DataLink `#this` row supplied the original IBE FITS URL; calibration and cutout rows were not selected.

The original contained PRIMARY, IMAGE, FLAGS, VARIANCE, ZODI, PSF and WCS-WAVE HDUs. The IMAGE was HDU 1, 2040×2040 pixels, with units MJy/sr. The file's UTC timestamp was 2026-06-24T03:19:00.063. Rendering masked 8,836 unusable/nonfinite pixels and retained 4,152,764 valid pixels.

Spatial WCS placed the requested target at approximately **x=37.815, y=546.095** in zero-based detector pixels, close to the left edge. The center's approximate wavelength was **1.337537 µm**, while the target's was **1.489988 µm**. These are distinct per-position values from the actual file's spectral WCS, not a uniform wavelength assigned to the image. The [live inspector screenshot](milestone-2-preview.png) shows the full detector frame and target cross.

The first original-file attempt hit a 180-second deadline and removed its partial file. A retry with 600 seconds succeeded. The final configurable default is therefore 600 seconds, with separate connect/read timeouts. Slow or unavailable IRSA service remains an explicit error condition, not a synthetic fallback.

## Scientific conventions and sources

The [official SPHEREx product guide](https://github.com/Caltech-IPAC/spherex-archive-documentation/blob/main/documentation/spherex_data_products.md) identifies IMAGE as science surface brightness, FLAGS as quality bits, and WCS-WAVE as the per-position spectral lookup. The [IRSA introduction tutorial](https://github.com/Caltech-IPAC/irsa-tutorials/blob/main/tutorials/spherex/spherex_intro.md) documents primary celestial WCS and alternate spectral WCS W, including disabling spatial SIP for wavelength evaluation. [IRSA flag documentation](https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/sp.html) identifies NONFUNC, DICHROIC and MISSING_DATA as bits 6, 7 and 9.

The viewer selects IMAGE by EXTNAME rather than by HDU number, inventories the other HDUs, retains the complete source file, and exposes the science/WCS-WAVE headers. Preview orientation is detector x-right/y-up, not north-up. A single PNG row reversal converts FITS row order to screen row order; pointer coordinates and target overlays use the inverse mapping. Preview downsampling and stretching never overwrite the FITS. Wavelength readouts are approximate visualization metadata; calibrated CWAVE/CBAND data remain necessary for scientific wavelength analysis.

## Failure handling tested

Synthetic MEFs have an empty primary HDU, intentionally reordered extensions, off-center celestial WCS, constant/invalid/flagged images and a small spectral lookup whose wavelength varies with both axes. Tests check original-file byte identity, target and pixel coordinates, spectral variation, missing/broken WCS, display orientation and resolution limits.

Mocked network tests exercise actual URL propagation, unique `#this` selection, host/path/credential/port restrictions, public DNS checks, blocked redirects, announced and streamed size limits, incomplete bodies, compressed HTTP responses, timeouts and partial-file removal. Cache tests cover reuse, expiry, eviction, continued streaming of an already-open original, and locks across service instances.

A malformed synthetic spectral table reference exposed a native WCSLIB abort during development. The final implementation validates references before construction and separates FITS processing into a child process. Decoder failure/timeout conversion is covered by tests; the final valid live file also rendered successfully through that isolated process.

## Scope and limits

- Exact trusted remote host: `irsa.ipac.caltech.edu`; unsupported hosts and ambiguous DataLink products fail explicitly.
- Defaults: 128 MiB per original, 3 cached entries, 1-hour idle expiry, 8 million science pixels, one image processing transaction at a time.
- The viewer supports the documented two-dimensional IMAGE product and uncompressed FITS containers. It does not render arbitrary cubes or select a different extension as a fallback.
- Headers/lookup tables and original science data are preserved; the display is not a photometry, reprojection, difference-imaging or moving-object-detection pipeline.
- The original can be large. Aborting the UI request does not necessarily stop the in-progress bounded server download. Busy, timeout, size-limit, missing-cache and unsupported-file responses are explicit.

## Changed files

- Added `backend/app/image_download.py`, `image_service.py`, `fits_image.py`, `fits_worker.py`, and `images.py`; registered the new routes/error handler in `main.py`. Existing `irsa.py` was not changed.
- Added `frontend/src/components/ImageInspector.jsx`; connected row selection/actions through `App.jsx` and `ObservationsTable.jsx`; extended `styles.css` using the existing palette. Existing sky-map and Aladin loader modules were not changed.
- Added `backend/tests/test_images.py`, browser image tests and tiny synthetic fixtures. Preserved the original test cases. Updated Vite/Playwright configuration to use isolated test ports and an optional API proxy target.
- Added Pillow to the Python requirements, ignored the local cache, and updated README and these verification notes.
