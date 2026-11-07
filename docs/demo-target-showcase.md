# Real SPHEREx target showcase

The offline bundle preserves M101 and adds selected QR2 native-detector cutouts. It is a **provenance and temporal-coverage showcase**, not a measurement of motion, variability, or comet activity. No WISE/NEOWISE images are included. Live Mode and the image services are unchanged.

## Discovery and selection

`demo/discovery/audit.json` records the complete metadata results, query/reference coordinates, response hashes, release partitions, detector counts, timestamps and time baselines. Raw VOTables are preserved alongside it. Counts mean **spectral-image records**, not source detections. Exact distinct `t_min` values are counted separately from observation IDs; detector timestamps can differ slightly. The audit also reports visits separated by more than one day. These definitions do not establish independent astrophysical variability epochs.

| Candidate | Image records | Exact start times | UTC coverage | Baseline, days | Decision |
|---|---:|---:|---|---:|---|
| 3I/ATLAS | 259 | 167 | 2025-08-01 – 2025-12-14 | 135.666 | QR2 D5; official predicted coordinates per exposure |
| RW Aurigae | 333 | 169 | 2025-09-01 – 2026-09-16 | 380.476 | QR2 D2 subset; unresolved young stellar system |
| R Draconis | 2,483 | 1,261 | 2025-04-24 – 2026-09-27 | 520.412 | QR2 wide-survey D2 subset; long-period variable context |
| Barnard’s Star | 359 | 182 | 2025-08-15 – 2026-09-22 | 402.763 | Not prepared; mission-era reference footprint only, source astrometry/detection still needs review |
| WISE 0855-0714 | 256 | 129 | 2025-05-05 – 2026-05-14 | 373.587 | Not prepared; catalog-designation position is not its current position; detectability unverified |

All five metadata sets include D1–D6 and collective product bounds approximately 0.7455–5.0096 µm. These are whole-product spectral bounds in metres in ObsCore, **not wavelengths measured at the target**. All report calibration level 2. RW Aur and Barnard include QR2/QR3; R Dra includes QR2 wide/deep and QR3 deep. Discovery coverage is larger than the prepared QR2-only selection. An initial R Dra query hit the row cap and was discarded; supported, complete point-in-footprint queries replaced rejected cone queries. Timeouts were not interpreted as zero coverage.

Source positions for RW Aur and R Dra identify catalog sky regions. Inclusion inside the cutout WCS is checked, but that does not establish a detected, uncontaminated source. Barnard’s query uses a mission-era region near the propagated position, not the obsolete J2000 position; no Barnard cutouts are delivered. WISE's reference-position count must not be presented as verified current-source coverage.

The comet observation table is supplied by IRSA and includes per-exposure `comet_ra`/`comet_dec`. No static comet coordinate is substituted. IRSA explicitly warns of low signal-to-noise at many wavelengths. Target-centered previews track the predicted position and retain native detector orientation; they are not registered fixed-sky frames and do not demonstrate measured comet displacement.

## Reproduce without changing the published bundle

```bash
# Metadata only; cached validated responses are reused.
.venv/bin/python scripts/discover_demo.py
# Optional new audit; preserves previous VOTables by content hash.
.venv/bin/python scripts/discover_demo.py --refresh
# Selected sequential cutouts; cache/public originals reused by checksum.
.venv/bin/python scripts/acquire_demo.py --targets 3i-atlas rw-aur r-dra --frames 6
# Preparation is OFFLINE and refuses an existing output directory.
.venv/bin/python scripts/prepare_demo.py --config demo/showcase-targets.json --output /tmp/new-showcase
.venv/bin/python scripts/validate_demo_science.py /tmp/new-showcase
# Rebuild the committed bundle entirely offline from preserved FITS/source records:
.venv/bin/python scripts/prepare_demo.py --config demo/targets.json --output /tmp/rebuilt-showcase
```

Acquisition requests only 0.12° IBE cutouts, never full-detector fallback. Each child operation has a hard 90-second wall-clock timeout, an 80-second downloader deadline and 16-MiB stream limit. Downloads are sequential, at most six frames per requested target per invocation, with no automatic retry. A failed invocation records failures; an explicitly rerun acquisition reuses successful files. Metadata is limited to 10,000 rows, 8 MiB and 60 seconds per target; cap hits and OVERFLOW are errors. One-off discovery retries used a 90-second bound. FITS response sizes cannot be predicted from parent-product `access_estsize`: small cutouts retain PSF and wavelength lookup extensions. Budget at most 96 MiB for six accepted requests per target; current cutouts are around 4.9 MiB each.

`demo/acquired/` is ignored staging. Published originals are served under content-derived image IDs and input source records remain in `demo/source-records/`. Manifest records add mission, QR release, calibration build from the returned product path, cutout center, position source/mode and discovery response digest. Original headers retain the detailed calibration history. SHA-256 verifies local bytes and reproducibility, not an independent archive signature.

## Scientific limits and scale

QR2 and QR3 are never mixed in a prepared sequence. Calibration build strings are retained per frame even within QR2; consistent release alone does not prove photometric equivalence. Selection keeps one detector per new target and temporal endpoints. Linear variable filters still change wavelength with detector position, so even same-detector animation is not a light curve. WCS-WAVE values are approximate; calibrated wavelength/response analysis, registration, PSF matching, background treatment, flags and photometry would be needed for scientific comparisons. Stellar components can be unresolved; saturation, persistence, blending and low S/N require additional source-specific review.

PNGs use the existing independent percentile/asinh renderer. Scientific arrays, FLAGS, VARIANCE and WCS-WAVE remain unchanged in original FITS. The marker represents a catalog/predicted coordinate transformed through WCS, not a measured centroid. The existing shared viewer and lazy temporal slider are reused; only selected local metadata/previews load. Original science FITS are downloaded by the browser only on explicit request or read locally by FastAPI for pixel inspection.

A local web server is still required; FastAPI provides local science-pixel reads. Demo Mode mounts no external Aladin atlas. For larger bundles, host immutable preview/FITS objects on static storage, retain a small versioned index, and preload only selected-target previews. Keep science originals separately accessible and retain content hashes. No server-side concurrency or Live Mode API changes are needed for this expansion.

## Sources

- [IRSA official comet table and interpretation guidance](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/comet3iatlas/index.html)
- [IRSA SPHEREx mission and release documentation](https://irsa.ipac.caltech.edu/Missions/spherex.html)
- [SPHEREx cutout service](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access/)
- [RW Aur catalog reference](https://archive.stsci.edu/prepds/starcat/StarCAT-summary/Table_1.pdf)
- [R Dra CDS position](https://aladin.cds.unistra.fr/simbad-thumbnails/thumbnails42.html)
- [Barnard’s Star SIMBAD astrometry](https://simbad.cds.unistra.fr/simbad/sim-basic?Ident=Barnard%27s+star)
- [WISE 0855 discovery and astrometry](https://doi.org/10.1088/2041-8205/786/2/L18)
