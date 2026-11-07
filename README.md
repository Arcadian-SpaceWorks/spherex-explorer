# Arcadian SkyTracker

Arcadian SkyTracker now includes Milestone 2: a real SPHEREx FITS image inspector, alongside the existing interactive celestial map and live observation discovery for a NASA Space Apps Challenge 2026 team prototype. This prototype does not claim NASA endorsement or detect Planet X.

## Run locally on Fedora

Prerequisites: Python 3.12+ (tested here with 3.14.8), Node.js 22.12+ (tested with 22.22.2), npm, internet access, and a WebGL2-capable browser. On Fedora, install missing runtimes with `sudo dnf install python3 python3-pip nodejs npm`.

From the repository root:

```bash
./scripts/setup.sh
```

Run these in separate terminals:

```bash
./scripts/backend.sh
```

```bash
./scripts/frontend.sh
```

Open http://127.0.0.1:5173. Backend API docs: http://127.0.0.1:8000/docs. Vite proxies `/api` to FastAPI on port 8000, so no permissive CORS configuration is needed. Both servers bind to loopback. Stop with Ctrl+C.

Equivalent commands after setup:

```bash
.venv/bin/python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
npm --prefix frontend run dev
```

## Use the map

- Drag to pan; scroll/pinch or use Aladin's controls to zoom.
- Click the sky to select an ICRS coordinate in decimal degrees. A mint cross marks the selection. Drag releases do not select a new target.
- Enter RA in `[0, 360)` and Dec in `[-90, 90]`, then choose **Go To Coordinates**. This selects and centers the target. The initial target is M101.
- The dashboard shows horizontal × vertical field of view in degrees, refreshed on zoom and resize.
- Choose **Search SPHEREx Observations** to query image footprints covering the selected point. Searching uses the selected location, not unsubmitted form edits or the map center.
- Changing the selected point clears results and cancels the previous request. Results are explicitly live, empty, or unavailable; the application contains no demonstration observations.

The background is the real DSS2 color HiPS optical survey rendered by Aladin, not SPHEREx imagery. The returned table contains SPHEREx observation metadata. Coverage alone is not a source detection or evidence of motion.

## Structure

```text
backend/
  app/main.py                   FastAPI routes and coordinate validation
  app/irsa.py                   IRSA TAP client, schema check, VOTable parsing
  app/images.py                 Image preparation, preview, pixel and download routes
  app/image_download.py         IRSA URL validation, DataLink resolution, bounded streaming
  app/image_service.py          Small local FITS/preview cache
  app/fits_image.py             Science HDU selection, display stretch, spatial/spectral WCS
  app/fits_worker.py            Isolated native decoder with resource limits
  tests/test_api.py             Existing observation API tests
  tests/test_images.py          Synthetic MEF, mocked download, cache and image API tests
  requirements.txt              Exact Python dependency versions
frontend/
  src/App.jsx                   Selection and request lifecycle
  src/aladin.js                 Version-pinned official npm API loader
  src/coordinates.js            Coordinate/click validation
  src/components/SkyMap.jsx     Genuine Aladin sky map and marker
  src/components/CoordinatePanel.jsx
  src/components/ObservationsTable.jsx
  src/components/ImageInspector.jsx
  src/styles.css                Responsive dark dashboard
  tests/coordinates.test.js     Coordinate and drag-release tests
  tests/browser/                Existing map checks, image UI tests, optional live FITS check
  tests/fixtures/               Small, explicitly synthetic browser-only MEF/PNG/JSON
  package-lock.json             Reproducible npm dependency resolution
scripts/                        Setup and local launch scripts
docs/                          API provenance and verification notes
```

## API and data semantics

```bash
curl 'http://127.0.0.1:8000/api/observations?ra=210.80227&dec=54.34895'
```

`GET /api/observations` requires finite numeric `ra` and `dec`. Invalid coordinates return HTTP 422. Successful upstream queries return HTTP 200 with `status: "live"`, input coordinates, provenance, `count`, `limit`, `truncated`, and `observations`. A valid zero-row response remains live. Service failures, schema changes, or invalid TAP responses return HTTP 503 with `status: "unavailable"` and an empty observation list, never fabricated substitutes.

The backend calls `https://irsa.ipac.caltech.edu/TAP/sync` with ADQL. On first use in each backend process it verifies the required columns against the service's `TAP_SCHEMA.columns`; only successful verification is cached. The data query selects at most 101 rows from `spherex.obscore`, uses `CONTAINS(POINT('ICRS', ra, dec), s_region)` for exact point-in-image-footprint matching, orders by newest start time, and returns up to 100 rows. A 101st row or TAP `OVERFLOW` sets `truncated: true`. This is a bounded metadata browser, not an exhaustive export. Synchronous queries have a 10-second connect / 50-second read timeout; the frontend has a 65-second deadline. Retry after an unavailable response. The first request can include schema-verification overhead.

Metadata: observation ID, collection, detector bandpass, image center RA/Dec, start UTC derived with Astropy from `t_min` MJD, exposure seconds, wavelength bounds converted from meters to micrometers, access URL and MIME type. Access links are IRSA DataLink metadata endpoints, not guaranteed direct FITS files. Missing values display `—`. There is a small local FITS file cache; there is no database, authentication, ML, or image differencing.

## View a real SPHEREx FITS image

Search the archive as before, then click **View Image** or select a row (Enter/Space also works). The inspector appears beneath the table. It downloads the exact `access_url` from the selected observation; for DataLink responses it follows the unique FITS `#this` product. It does not construct product URLs or substitute calibration files/cutouts. The first load may take several minutes. Reopening a cached image is much faster.

- Use + / −, Fit image, drag, or the arrow buttons to zoom and pan the preview.
- Click an image pixel for its original surface brightness, flags, ICRS position, and approximate wavelength/bandwidth where the file supports them.
- The mint target cross is computed from the original spatial WCS. An outside-image target or missing WCS is reported explicitly. The full image is not recentered or rotated to north-up; native detector x increases right and y increases up. UI pixel coordinates are zero-based.
- `IMAGE` is selected by extension name after inspecting the HDUs, regardless of extension order. The primary HDU is not assumed to contain science pixels. Expand **FITS HDUs and WCS metadata** to inspect the inventory and headers.
- The grayscale PNG is a visualization only: 1st–99th percentile limits, asinh `a=0.1`, and nearest-neighbor downsampling to a maximum dimension of 1024. Nonfinite/masked pixels and documented FLAGS bits 6/7/9 (NONFUNC, DICHROIC, MISSING_DATA) are transparent. Other quality flags remain visible and can be inspected. All-invalid images fail explicitly; constant valid images display neutral gray.
- Wavelength varies over the detector. Archive wavelength bounds describe the observation, not every pixel. Readouts use the file's alternate spectral WCS `W` and `WCS-WAVE` table with spatial SIP distortion disabled for that spectral transformation. Missing/unsupported spectral metadata remains unavailable. These approximate values support visualization; scientific wavelength analysis needs the calibrated CWAVE/CBAND products.
- **Download original FITS** streams the unchanged, complete cached file, including every HDU, WCS and lookup table. The API also returns its SHA-256 checksum. Reload the observation if the cache entry has expired. No zodiacal subtraction, reprojection or scientific pixel modification is performed.

The existing setup and launch commands still apply. Re-run `./scripts/setup.sh` after updating to install the added Pillow dependency.

### Quick cutouts (default) and full detector images

By default the inspector asks IRSA for a **cutout**: a small square (0.3 degrees wide) centred on your selected target, instead of the whole detector file. IRSA's cutout method is to append `?center=RA,DEC&size=0.3000deg` to the product URL that DataLink returns, so the backend does exactly that (see `add_cutout_query` in `backend/app/image_download.py`). Cutouts are much smaller than full files (about 4 MB in our first live test) and load in roughly 20 seconds. The **Full detector image (slow)** button restores the previous behaviour.

- The cutout is saved and served like any other image, with its own cache entry (the cache key includes the target and size). The downloaded FITS is the cutout, not the full file, and the UI labels it as such with its source URL.
- A cutout is still an IRSA product: the host and path allowlist applies to the cutout URL too, and only validated finite numbers are placed in the query.
- If the server is busy with another file, the UI waits a few seconds and retries (up to four times) instead of failing immediately.
- Not verified against live IRSA in the test suite (tests mock the network). Run `.venv/bin/python scripts/smoke_cutout.py` once with internet to check it end to end. Check in particular whether wavelength readouts are available in cutout files.

### Pair suggestions for time comparison (backend)

`GET /api/pairs?ra=10.6847&dec=41.2687&band=SPHEREx-D1&per_visit=2` suggests pairs of observations of the same sky point that are fair to compare over time. It is backend-only for now; a comparison view in the frontend is the next step.

1. Searches **one band** (`band=SPHEREx-D1` to `SPHEREx-D6`). The observation search also accepts `band` now, because without it the newest 100 rows of all bands can hide the older survey passes that a time comparison needs.
2. Groups the results into **visits** (runs separated by more than 20 days).
3. **Shortlists** up to `per_visit` observations per visit whose image centre is closest to the target. This is a heuristic to limit downloads.
4. Fetches a **cutout** for each shortlisted observation (about 20 s each on first use; cached afterwards; cutouts have their own cache limit, `SKYTRACKER_CUTOUT_CACHE_ENTRIES`, default 30) and reads the **wavelength at the target pixel**.
5. Ranks pairs at least 1 hour apart: **ACCEPT** when the target wavelengths differ by at most 0.02 micron (blink and difference image are fair), **WARN** when they differ more or one is unknown (blink only, with the reason). Each pair says whether it is within one visit or between visits.

Because SPHEREx uses linear variable filters, the same band name does not mean the same wavelength at the target, so the measured wavelength decides. A suggestion is not evidence of motion or of any new object. Try it live with `.venv/bin/python scripts/smoke_pairs.py` (first run can take a few minutes; the second should be quick).

### Image endpoints and limits

`POST /api/images` accepts `{ "access_url": "<actual IRSA metadata URL>", "ra": 210.80227, "dec": 54.34895 }`. RA/Dec are optional as a pair and used only for locating the selected target. Add `"cutout_deg": 0.3` (0.02 to 1.0, requires RA/Dec) to request an IRSA cutout of that width instead of the full file. The response contains the image identifier, preview/original URLs, HDU inventory, scaling, WCS metadata, image-center readout and target position.

- `GET /api/images/{id}/preview`: derived RGBA PNG.
- `GET /api/images/{id}/original`: original FITS attachment, streamed from disk.
- `GET /api/images/{id}/pixel?x=37&y=546`: zero-based pixel and WCS readout.

Only HTTPS on the exact `irsa.ipac.caltech.edu` host, port 443, and the SPHEREx DataLink/product path prefixes is accepted. Credentials, other hosts/IP literals, traversal paths and non-public DNS addresses are rejected. Each redirect and DataLink destination is checked again. Environment proxies and `.netrc` credentials are disabled for this public-file downloader. No remote URLs are passed to Astropy.

Downloads use 64 KiB chunks, a 10-second connect timeout, 30-second read timeout and a configurable overall deadline checked between chunks. Both announced lengths and actual streamed bytes are limited; partial failures are removed. DataLink tables have a separate 2 MiB bound. Only uncompressed FITS containers are supported. The frontend waits up to 12 minutes for preparation; changing the row or sky target cancels the UI request, while an already-running server download may finish within its bound and populate the cache.

Configure these environment variables **before starting the backend**:

| Variable | Default | Meaning |
| --- | --- | --- |
| `SKYTRACKER_FITS_MAX_BYTES` | `134217728` | 128 MiB per original FITS download |
| `SKYTRACKER_FITS_DOWNLOAD_SECONDS` | `600` | Overall remote-download deadline, seconds |
| `SKYTRACKER_FITS_CACHE_DIR` | repository `.cache/arcadian-fits-v1` | Cache directory; an absolute override is recommended |
| `SKYTRACKER_FITS_CACHE_ENTRIES` | `3` | Maximum completed originals/previews |
| `SKYTRACKER_FITS_CACHE_TTL` | `3600` | Idle expiry, seconds |
| `SKYTRACKER_FITS_MAX_PIXELS` | `8000000` | Maximum science-image pixels before loading its array |

All numeric limits must be positive. Originals occupy at most entry count × maximum file bytes, plus small previews/metadata. Cache pruning occurs on access; expired entries and stale partial directories are removed. Thread and file locks serialize download/decoding work; a concurrent request returns a retryable 503 instead of queueing large jobs. Open file downloads remain valid even if their cache entry is subsequently evicted. Cache files are ignored by Git.

FITS/WCS processing runs in a child process with a 60-second wall limit, 55-second CPU limit, 3 GiB address-space limit and no core dumps, so malformed native-decoder input does not terminate the API. The default scripts target Linux/Fedora. The API returns explicit errors: 400 unsafe URL; 413 file/pixel limit; 422 unsupported/invalid/all-masked FITS; 404 cache miss; 502 upstream/decoder failure; 503 busy; 504 timeout; 507 cache unavailable.

## Tests and build

```bash
.venv/bin/python -m pytest backend/tests -q
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:browser
```

Browser tests use installed Chrome at `/usr/bin/google-chrome`; override with `CHROME_PATH=/absolute/path/to/chrome`. They launch dedicated Vite and FastAPI servers on ports 5174 and 8001; the live search test queries the real IRSA archive. Real map tests require internet and WebGL; they exercise the official pinned Aladin API, rather than a mocked sky map. API unit tests use labeled test fixtures and do not require IRSA availability. See [verification notes](docs/verification.md) for checks actually run.

The full-file live browser test is opt-in because it can download roughly 70 MB:

```bash
SKYTRACKER_LIVE_FITS=1 npm --prefix frontend run test:browser
```

The other image-browser tests use clearly labeled synthetic MEF/PNG fixtures and mocked image HTTP responses. These fixtures are never loaded by the application itself. See [Milestone 2 verification](docs/milestone-2.md) for actual checks and limitations.

`frontend/dist/` is the production frontend build. To serve it elsewhere, configure the same-origin `/api` reverse proxy to FastAPI. Deployment is outside this local milestone.

## Official sources and attribution

- [Aladin Lite official API documentation](https://cds-astro.github.io/aladin-lite/), [stable v3.8.1 release](https://github.com/cds-astro/aladin-lite/releases/tag/v3.8.1), [pinned JavaScript build](https://aladin.cds.unistra.fr/AladinLite/api/v3/3.8.1/aladin.js).
- [IRSA SPHEREx help](https://irsa.ipac.caltech.edu/onlinehelp/spherex/help.pdf) documents `spherex.obscore`.
- [Official SPHEREx archive data access documentation](https://github.com/Caltech-IPAC/spherex-archive-documentation/blob/main/documentation/spherex_data_access.md).
- [Official IRSA TAP service documentation](https://irsa.ipac.caltech.edu/TAP/) and [IRSA SPHEREx footprint-query tutorial](https://github.com/Caltech-IPAC/irsa-tutorials/blob/main/tutorials/spherex/spherex_cutouts.md).
- [Schema verification details](docs/data-sources.md).

Aladin Lite is developed by CDS, Strasbourg Observatory. Its built-in bottom-right logo/link remains intact and unobscured. DSS2 HiPS tiles are loaded from the [STScI public mirror](https://stpubdata.s3.us-east-1.amazonaws.com/mast/skybackgrounds/DSSColor/properties), listed in the [official CDS survey registry](https://alasky.cds.unistra.fr/MocServer/query?ID=CDS%2FP%2FDSS2%2Fcolor&fmt=html&get=record). DSS2 survey attribution is available through Aladin's survey information. SPHEREx metadata is served by NASA/IPAC IRSA. Survey tiles and IRSA need network connectivity; Aladin JS/CSS/WebAssembly are bundled locally after installation; map failure is explicitly reported and never replaced with a simulated star field.

SPHEREx image conventions: [official product guide](https://github.com/Caltech-IPAC/spherex-archive-documentation/blob/main/documentation/spherex_data_products.md), [IRSA spatial/spectral WCS tutorial](https://github.com/Caltech-IPAC/irsa-tutorials/blob/main/tutorials/spherex/spherex_intro.md), and [pixel flag definitions](https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/sp.html).
