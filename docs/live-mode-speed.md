# Live Mode speed: S3 mirror, local IRSA-identical cutouts, non-blocking cache

Demo Mode is unaffected: it reads the preloaded bundle and never downloads.

## What was slow

Live Mode already asked IRSA for server-side cutouts (`?center=<ra>,<dec>&size=<deg>deg`), never full
files by default. The limit was IRSA's delivery rate. Measured from our deployment (one product,
`qr2/level2/2026W21_2A/.../level2_2026W21_2A_0213_2D5_spx_l2b-v25-2026-147.fits`):

| Route | Time | Bytes |
| --- | --- | --- |
| IRSA cutout, 0.3° | 21–23 s | 5.6 MB |
| IRSA full product | 249 s | 72 MB |
| AWS mirror, full product | 3–5 s | 72 MB |

A cutout is about 5.5 MB, not kilobytes, because IRSA copies the whole 121×101×101 PSF cube (81 % of
the bytes) into every cutout. Three more costs added up: one lock covered every download, so a slow
image blocked everyone's previews and pixel readouts; only 3 cutouts were cached for an hour; and the
pair search and each comparison fetched their images one after another.

## What changed

1. **Mirror first, IRSA as fallback** (`MirrorDownloader`, `backend/app/image_download.py`). DataLink
   still comes from IRSA (cached in memory). The product path under `/ibe/data/spherex/` is the same
   key on `https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/` (AWS Open Data, anonymous HTTPS).
   The full product is downloaded once, its size checked against IRSA's DataLink `content_length`,
   and kept briefly (4 products by default) so the viewer cutout, the comparison cutout and pair
   suggestions of one exposure share it. Any mirror problem (missing object, outage, size mismatch,
   unreadable file) falls back to IRSA's own cutout. The mirror host has its own exact allowlist
   (HTTPS, one host, `qr*/level2/*.fits`).
2. **Local cutouts identical to IRSA's** (`backend/app/local_cutout.py`), made in the sandboxed decoder
   process. IRSA's cutout keeps all HDUs in order; planes with the IMAGE shape are sliced and only
   `NAXIS1/2`, `CRPIX1/2`, `CRPIXnA` and `CRPIXnW` change, by the slice offset; PSF and WCS-WAVE are
   copied unchanged. QR3 products store FLAGS tile-compressed (and the PSF as an `EPSF` table); IRSA
   writes the cut FLAGS as a plain image, and so do we, decompressing only the needed tiles. The box is, per axis, `n = round(size / pixel scale of that axis)` pixels (the
   column norms of the WCS pixel-scale matrix) starting at `ceil(centre − n/2)`, with the centre from
   the full SIP WCS and the box clipped to the detector. Because the bytes are identical, the SHA-256,
   the recorded `fits_url` (the equivalent IRSA cutout URL) and every downstream result are unchanged;
   `delivery` in the image metadata records which route was used.
3. **No global blocking** (`ImageService`). Downloads and decoding run outside the cache lock; the lock
   covers only lookup, pruning, publishing and reading. Requests for the same image share one
   download; at most 3 preparations run at once, with a bounded queue (503 when full, as before).
4. **Larger cache**: 48 cutouts (about 6 MB each) for 6 hours by default.
5. **Fewer waits**: pair candidates are prepared 3 at a time; comparisons fetch A and B together; a new
   image needs one decoder start for preview and target instead of two; the live time slider asks the
   server to prepare the next observation once the current one is shown.

## Evidence

- `backend/tests/test_mirror.py` (no network): re-cutting each unclipped IRSA cutout in the demo bundle
  reproduces it byte for byte; worker cutouts keep data, PSF, WCS-WAVE and the target's sky position;
  fallback, allowlist, cache bounds, single download per product, non-blocking cache, parallel pairs.
- `scripts/check_mirror_cutouts.py` (network): rebuilds every demo cutout from the mirror and compares
  SHA-256 with the IRSA original. Result on 2026-11-08: **60 of 60 identical** (53 QR2, 7 QR3; M101,
  M31, Barnard's Star, 3I/ATLAS; 0.3° and 0.437°; including cutouts clipped at the detector edge). The
  first run found the 7 QR3 files different, which exposed the compressed-FLAGS case above.
- Measured end to end with the real service: a new 0.3° view took 7.9 s (IRSA route: about 21 s plus
  decoding), with the SHA-256 of IRSA's cutout; a 0.437° comparison cutout of the same exposure then
  took 2.3 s; a repeat view is a cache hit. Through the API, a comparison of two uncached live images
  (Barnard's Star, D3, August 2025 and August 2026) took 10.1 s; by the IRSA route each image alone
  takes about 21 s.

Parallel ranged downloads did not beat one stream (the connection is already saturated at about
20 MB/s), and range-reading only the needed rows would save bandwidth but need several sequential
round trips and lose the shared full product, so neither is used.

## Settings

`SKYTRACKER_S3_MIRROR=0` turns the mirror off (IRSA only). `SKYTRACKER_SOURCE_CACHE_ENTRIES` (default 4)
bounds kept full products (about 72 MB each, under the image cache directory in `.sources/`).

## Download panel

In Live Mode a panel fixed to the corner of the screen lists every search and image preparation the
server is working on (`GET /api/images/progress`, `backend/app/progress.py`). It reports measured
facts only: the stage, bytes received and, when the remote server states it, the total. The AWS mirror
states a size, so those downloads show a percentage. IRSA's cutouts state none, so a fallback shows
"MB so far" and a moving bar, never an invented percentage. A cache hit downloads nothing and adds no
row. The list covers the whole server and holds observation names only, without coordinates. Demo
Mode downloads nothing and never asks for it.
