# Real SPHEREx target showcase

The offline bundle preserves M101 and adds selected QR2 native-detector cutouts. It is a **provenance and temporal-coverage showcase**, not a measurement of motion, variability, or comet activity. No WISE/NEOWISE images are included. Live Mode and the image services are unchanged.

## Larger sets: M31, Barnard's Star and 3I/ATLAS

Demo Mode also holds about twenty 0.437° cutouts for each of three targets, chosen by `scripts/acquire_demo_targets.py` from saved discovery tables (`demo/discovery/m31.vot`, `barnard.vot`, `3i-atlas.vot`). 0.437° is the size `/api/compare` needs to fill its north-up 0.3° grid. `demo/plans/<target>.json` lists every candidate that was downloaded, whether it was selected and why, with its wavelength at the frame centre and at the marker.

| Target | Frames | What is in it | Wavelength-matched pairs (Δλ ≤ 0.02 µm at the target) |
|---|---:|---|---|
| M31 core | 18 | Three survey passes (Jul 2025, Dec 2025, Jul 2026), QR2 only; one exposure per detector in each pass. D1/D4 are the curated exposures checked by `scripts/smoke_compare.py`; D2 and D3 were chosen from four candidates per pass; D5/D6 are their simultaneous partners. | D1 Dec 2025 ↔ Jul 2026 (0.0011 µm), D2 Jul 2025 ↔ Dec 2025 (0.0195 µm), D3 Dec 2025 ↔ Jul 2026 (0.0134 µm) |
| Barnard’s Star | 21 | D3, seven frames at each of three epochs (Aug 2025 and Mar 2026 from QR2, Aug 2026 from QR3), from twelve candidates per epoch; 370-day baseline. | Six seeded pairs, two per pair of epochs: Aug 2025 ↔ Aug 2026 within 0.018 µm, Aug 2025 ↔ Mar 2026 within 0.006 µm, Mar 2026 ↔ Aug 2026 within 0.012–0.015 µm |
| 3I/ATLAS | 18 | All twelve D5 exposures of the 14 Dec 2025 tracklet (04:27–07:46 UTC, three groups of four) and six of the simultaneous D2 frames. | None: the wavelength at the centre steps by about 0.035 µm per exposure (D5 3.96 → 4.35 µm), so time comparisons stay side by side |

**Comparing them.** In Demo Mode the A/B buttons send the preloaded image IDs to `POST /api/compare`, which reads the original FITS from the local bundle. Checked offline: Barnard D3 Aug 2025 ↔ Aug 2026, Aug 2025 ↔ Mar 2026 and Mar 2026 ↔ Aug 2026, and M31 D1, D2 and D3 pairs, are ACCEPTed with difference images (overlap 98–99%); comet D5 frames hours apart are WARN (wavelength mismatch, blink only); two bands of one exposure are side by side.

**Selection rules.** Candidates come from fixed epoch windows, with one data release per epoch (a mixed epoch is refused) and an evenly spaced number of candidates per detector. After download, each frame's coverage of the 0.3° comparison grid is measured with the same loading and resampling as `/api/compare`. Pairs across epochs whose wavelength at the target agrees within 0.02 µm and that each cover at least 95% of the grid (so the pair overlaps by at least the 90% `/api/compare` requires) are kept first, longest baseline first; the remaining places are spread in time, preferring frames that cover the grid. Coverage matters because the extremes of a detector's wavelength range lie at its edges: a frame whose target sits at 2.41 µm in D3 is clipped to about 43% of the grid. For M31 the simultaneous partner detector (D4, D5 or D6: the same exposure through the dichroic) is then added to each selected frame.

**Fixed sky with predicted positions.** Barnard's Star and 3I/ATLAS each use one fixed cutout centre, so background stars stay in place and the moving source changes position. Every frame records the source's predicted position at that exposure (`acquisition.predicted_ra` / `predicted_dec`), and that is where the marker is drawn. For the comet it is IRSA's official `comet_ra`/`comet_dec`. For Barnard's Star it is the Gaia DR3 astrometry of source 4472832130942575872 (saved in `demo/discovery/barnard-gaia-dr3.csv`) propagated linearly by its proper motion; annual parallax (up to 0.55″) and perspective acceleration are ignored, both under 0.1 pixel. The marker is never a measured position. The comet's centre is the mean of its predicted path for the selected exposures (RA 167.2031°, Dec +5.1481°); the comet stays within 0.082° of it, inside the comparison grid. Barnard's centre is its Gaia position on 2026-03-01.

**Barnard's Star mixes two releases.** Barnard's August 2026 visit is only in QR3, so a one-year baseline needs QR3 for the last epoch while the first two come from QR2. Each epoch uses one release, every frame records its release and calibration build, and Demo Mode states the mix. Positions can be compared across releases; brightness should not be. The star saturates its core (OVERFLOW flags), so a single-frame centroid scatters by 1–2″. A preparatory test (centroids in a 13×13-pixel box; three QR2 frames from August 2025, four QR3 frames from August 2026) measured 9.2″ per year against Gaia's 10.39″.

Reproduce (needs internet; staged frames and frames already in the bundle are never downloaded again):

```bash
.venv/bin/python scripts/acquire_demo_targets.py            # all three, or name some: m31 barnard 3i-atlas
.venv/bin/python scripts/prepare_demo.py --config demo/acquired/staging-targets.json --output /tmp/new-demo
.venv/bin/python scripts/validate_demo_science.py /tmp/new-demo
# After replacing frontend/public/demo with /tmp/new-demo:
.venv/bin/python scripts/acquire_demo_targets.py --publish  # demo/targets.json reads the published FITS
```

## Discovery and selection

`demo/discovery/audit.json` records the complete metadata results, query/reference coordinates, response hashes, release partitions, detector counts, timestamps and time baselines. Raw VOTables are preserved alongside it. Counts mean **spectral-image records**, not source detections. Exact distinct `t_min` values are counted separately from observation IDs; detector timestamps can differ slightly. The audit also reports visits separated by more than one day. These definitions do not establish independent astrophysical variability epochs.

| Candidate | Image records | Exact start times | UTC coverage | Baseline, days | Decision |
|---|---:|---:|---|---:|---|
| 3I/ATLAS | 259 | 167 | 2025-08-01 – 2025-12-14 | 135.666 | QR2 D5; official predicted coordinates per exposure. Demo Mode: the 14 Dec 2025 tracklet on a fixed sky centre (above) |
| RW Aurigae | 333 | 169 | 2025-09-01 – 2026-09-16 | 380.476 | QR2 D2 subset; unresolved young stellar system |
| R Draconis | 2,483 | 1,261 | 2025-04-24 – 2026-09-27 | 520.412 | QR2 wide-survey D2 subset; long-period variable context |
| Barnard’s Star | 359 | 182 | 2025-08-15 – 2026-09-22 | 402.763 | Prepared later: D3 at three epochs with Gaia-predicted positions (see the larger sets above) |
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

The original showcase selection never mixes QR2 and QR3 in a prepared sequence; Barnard's Star (above) is the one disclosed exception. Calibration build strings are retained per frame even within QR2; consistent release alone does not prove photometric equivalence. Selection keeps one detector per new target and temporal endpoints. Linear variable filters still change wavelength with detector position, so even same-detector animation is not a light curve. WCS-WAVE values are approximate; calibrated wavelength/response analysis, registration, PSF matching, background treatment, flags and photometry would be needed for scientific comparisons. Stellar components can be unresolved; saturation, persistence, blending and low S/N require additional source-specific review.

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
