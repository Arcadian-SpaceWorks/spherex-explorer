# Hybrid live / preloaded presentation

Open `http://127.0.0.1:5173/?mode=demo` after starting the existing backend and
frontend with `scripts/backend.sh` and `scripts/frontend.sh`. The selector also
switches modes without reloading. Live remains the default at `/`.
Demo needs a running local static server; local science pixel readouts additionally
need FastAPI. It does not require internet, IRSA, or the runtime FITS cache.
This is not a service worker that makes an unreachable remote website available.
Use localhost or HTTPS (metadata SHA-256 verification uses Web Crypto).

## Prepared inventory and scientific limits

`frontend/public/demo/manifest.json` lists two astronomical targets with coordinate
references: M101 (ready), M31 (ready). M101's selected point is the existing
application region at ICRS 210.802270°, +54.348950°. The coordinate reference identifies
the named galaxy; the selected region is not asserted to be an exact catalog centroid.
References: [M101](https://simbad.cds.unistra.fr/simbad/sim-basic?Ident=M101),
[M31](https://simbad.u-strasbg.fr/simbad/sim-basic?Ident=m31).

Three existing real IRSA cutouts were successfully prepared, about 16 MiB of FITS
plus small PNGs/JSON. They represent **two epochs and three detector frames**, not
three distinct observing times:

| FITS observation ID | FITS UTC | Detector | Center wavelength (approx. µm) |
| --- | --- | --- | --- |
| 2026W21_2A_0213_2 | 2026-05-22T19:40:19.088Z | 5 | 4.3663 |
| 2026W21_2A_0213_3 | 2026-05-22T19:42:28.021Z | 2 | 1.6305 |
| 2026W21_2A_0213_3 | 2026-05-22T19:42:28.021Z | 5 | 4.4002 |

M31 (ICRS 10.684708°, +41.268750°) has six real IRSA cutouts of **0.437°**, the size
`/api/compare` needs to fill its north-up 0.3° grid, about 36 MiB of FITS. They are the
three survey passes validated by `scripts/smoke_compare.py`, each in D1 and in D4 of the
**same exposure** (imaged at the same moment through a dichroic):

| FITS observation ID | FITS UTC | D1 wavelength at M31 (approx. µm) | D4 wavelength at M31 (approx. µm) |
| --- | --- | --- | --- |
| 2025W28_1B_0480_4 | 2025-07-09T14:56:47.965Z | 0.7502 | 2.4419 |
| 2026W01_1A_0471_1 | 2025-12-31T06:00:22.121Z | 0.8946 | 2.9799 |
| 2026W28_2A_0117_1 | 2026-07-10T00:02:31.613Z | 0.8935 | 2.9751 |

Brightness differences between passes follow the wavelength at the target (linear variable
filters), not time; no variability is claimed. `scripts/acquire_m31_demo.py` re-downloads the
set through the app's `ImageService` (sequential, checksummed, resumable) into the ignored
`demo/acquired/m31/` staging folder and writes the source records; `demo/targets.json` then
points at the published originals so the bundle rebuilds offline byte-for-byte.

The original DataLink and IBE cutout URLs are retained per frame. Preparation
verified FITS header IDs, times (explicit TIMESYS=UTC), detectors, source-record SHA-256, URL identity,
cutout parameters, and target inclusion through celestial WCS. These are checks
of already downloaded data and recorded provenance; they do not independently
re-fetch or authenticate the archive origin. Raw cache source records are retained
in `demo/source-records/`. No new archive downloads were made for this feature.

Returned FITS bytes, headers, FLAGS, VARIANCE, ZODI, PSF and WCS-WAVE HDUs are kept.
PNGs are display representations, never photometric arrays. Per-frame percentile
stretching prevents interpreting pixel brightness differences as variability.
Different detector wavelengths, orientation and coverage prevent assuming image
registration. No motion, transient, or brightness variation has been validated.
Missing calibrated spectral bounds/exposure values remain null, not inferred from
approximate center wavelength. WCS-WAVE wavelength/bandwidth readouts retain their
existing approximate designation.

## Reproducible preparation and validation

```bash
.venv/bin/python scripts/prepare_demo.py --validate frontend/public/demo
.venv/bin/python scripts/prepare_demo.py --config demo/targets.json --output /tmp/skytracker-demo-rebuilt
```

The inventory uses configuration-relative paths to preserved FITS and source
records, not disposable runtime cache entries. Output must be a **new directory**;
preparation refuses to overwrite existing bundles or alter source files. A failure
never publishes a partial bundle. Rebuilding with the pinned dependencies and
renderer produces identical bytes; dependency versions and renderer source hash
are recorded in provenance. Validate a new bundle before deliberately deploying
it under `/demo/`. Keep a copy of the preserved FITS when replacing a bundle.

To add another target, supply local, already bounded cutouts and their
source records in the inventory; do not invent observation metadata. The script
has no network code and a 128 MiB per-input cap. It invokes the existing isolated
FITS renderer (8 million science pixels, CPU/time/memory bounds), generates PNGs
with a maximum 1024-pixel side, then publishes after validation. It rejects
checksum mismatches, mismatched source identities, missing UTC/detector metadata,
unsupported cutouts and targets outside their supplied WCS footprint.

`demo/manifest.schema.json` is generated from the Pydantic `Manifest` model in
`backend/app/demo.py`. Schema version 1 permits 2–3 targets, explicit ready/missing
states, validated source URLs, UTC timestamps, detector/spectral fields, local
asset paths, checksums and processing provenance. `--validate` checks file
existence, checksums and metadata/manifest consistency. The frontend independently
checks the schema fields and local paths and verifies metadata SHA-256 before use.
A digest checks consistency, not archive authenticity or protection against an
attacker replacing an entire bundle; distribute through a trusted release.

## Runtime architecture and scaling

`App` selects a live observation result or a normalized local manifest result.
`imageAdapter` routes both the existing slider and inspector to either the live
`POST /api/images` or local metadata. Demo PNGs and FITS downloads are static paths;
viewing/switching a frame requires no FITS parsing, IRSA call, or live cache lock.
Aladin is mounted only in Live Mode, so starting directly in Demo Mode does not
request sky-survey tiles. Live cutout/full-image behavior is preserved.

The optional `/api/demo/images/{id}/pixel` endpoint looks up a manifest-approved
local FITS, checks its checksum, and invokes the existing scientific decoder.
Two concurrent demo readouts are allowed, independently of live preparation.
Missing/corrupted FITS produces an explicit error, never a live download or PNG
pixel substituted for science data. `SKYTRACKER_DEMO_DIR` can point the backend to
another validated bundle; static hosting must serve the same bundle under `/demo/`.

For more targets, publish versioned manifests and immutable assets to static
hosting/object storage with checksum-based cache keys. Load a compact catalog
first and split per-target metadata; retain selected-frame lazy loading and at
most neighboring preview prefetch. Keep larger FITS in a scientific archive tier
and the small preview tier available to presentation clients. Add quotas and a
bounded job queue for acquisition/preparation; never run bulk preparation in an
interactive request. Measure cold/warm preview latency and bundle sizes before
adding progressive or tiled rendering. Current demo metadata is fetched per
selection and fits comfortably in memory; this is not a bulk browser FITS cache.

## Verification

The backend suite covers deterministic preparation, byte-for-byte reproduction,
source mismatches, invalid manifests, missing/corrupted files, source FITS retention
and offline local pixel readout. Frontend unit tests cover manifest/path checks,
chronology, adapter routing and missing/corrupt metadata. Browser tests block
external network access and cover real local playback, pixel readout, target and
mode switching, missing manifests/previews, retries and mobile width, alongside
existing live viewer/slider regressions. The mode-switch test intentionally blocks
Live Mode's survey requests; the expected Aladin network errors do not prevent
returning to Demo Mode. Live archive access was not retested for this feature.

Final checks for this implementation: **102 backend tests passed** (one existing
Starlette/httpx deprecation warning), **3 frontend unit test files passed**,
**15 focused browser tests passed**, and **production build passed** (existing
Aladin bundle-size warning). Offline rebuilding of the real bundle reproduced all
10 files byte-for-byte, including after explicit UTC verification. The three PNGs
total 172,182 bytes; preserved FITS total 16,571,520 bytes. No new live datasets were
acquired at that time. (M31 was prepared later; see the M31 table above.)
