# Spectral fingerprints: the spectrum of any point in the sky

## Why this is the new core of the project

SPHEREx is not a camera that happens to have filters. Its linear variable filters make the
wavelength change across each detector, so one exposure measures a given sky point at **one**
wavelength, and the survey steps the sky across the filters until every point has been measured at
about a hundred wavelengths from 0.75 to 5 µm. The archive holds roughly 330 to 600 exposures of an
ordinary sky point, and more near the ecliptic poles.

The earlier milestones compared pairs of exposures as images. That comparison has to fight the
instrument: two exposures of the same place almost never share a wavelength, which is why pair
suggestions needed a 0.02 µm matching rule and most pairs were rejected. Reading the same exposures
as a **spectrum** uses all of them, and uses them for what the mission was built to do:

- **What is it made of?** Water, carbon dioxide and carbon monoxide ice, CO2/CO/H2O gas from comets,
  PAH dust and hydrogen lines all fall in this range. Most of it is blocked by Earth's atmosphere.
- **Did it change?** Every point is revisited about every six months, so the spectrum is a
  spectrum in time. Brightness is compared between seasons at matching wavelengths.
- **How far is it?** Emission lines of galaxies and quasars slide through the range with redshift.

The image tools remain, below the spectrum, as the way to inspect the individual exposures behind
any point of it.

## How a spectrum is measured

1. **One archive query** (`backend/app/spectrum/archive.py`) asks IRSA's TAP service for every
   Level 2 exposure whose footprint contains the position: `spherex.plane` joined to
   `spherex.artifact` with `CONTAINS(POINT, p.poly)`. The reply carries the archive path of each
   product, so no path is guessed and no DataLink round trip is needed. About 5 to 15 s.
2. **Range reads, not downloads** (`remote.py`). Products are about 70 MB each. They are public on
   the AWS Open Data mirror of the archive, which honours HTTP range requests, so each exposure costs
   a few small reads: the headers, 9 detector rows of the IMAGE, FLAGS and VARIANCE planes around
   the target, and the WCS-WAVE table at the end of the file. That is about 0.3 MB per exposure,
   read by 32 threads. Every HDU offset is derived from the headers that were read and each header
   is checked for its extension name; QR3's tile-compressed FLAGS are read row by row and
   decompressed by astropy.
3. **Forced aperture photometry** (`photometry.py`) at the requested position in each exposure:
   radius 2.5 px (15.4″) with sub-pixel edge weights, no recentring. The local background is the
   sigma-clipped median of the pixels 6 to 12 px away within the 9 rows around the target, which
   removes zodiacal light without the ZODI model and stays at nearly the target's own wavelength.
   Uncertainty: the pipeline VARIANCE plane summed over the aperture plus the background term.
   The wavelength is read for the target's pixel from that exposure's own WCS-WAVE table.
4. **Honest rejection.** A measurement with a transient, overflow, non-functional, hot, cold,
   non-linear, persistence or streak flag inside the aperture is kept in the table and the CSV with
   its reason, and never plotted as a flux. `OUTLIER` is kept as a note only: the pipeline sets it on
   anything that differs from the static sky, which includes comets and sources that changed.
5. **Analysis** (`analysis.py`), all measured from the points, nothing fitted to a template:
   - *Bands.* Each band has a core window and two continuum windows. The band strength is the median
     offset of the core from a straight line through the side-window medians. It is reported only
     above 5σ **and** 8 % of the continuum, when the core points agree with each other, and when the
     core stands out from **both** side windows. "Not found" and "not enough exposures to test" are
     reported separately. A band that removes nearly all the light gives a lower limit on optical
     depth.
   - *Seasons.* Exposures separated by more than 20 days belong to different seasons. Each season is
     compared with the best-observed one using only points in the same detector within half a
     resolution element in wavelength. A change is reported above 8 % and 5σ. Moderate changes are
     scaled out before bands are measured; when a source changed by more than 50 % each season is
     analysed alone.
   - *Moving targets* are measured at the position predicted for each exposure and tested for gas
     emission only (a comet's sunlight-plus-thermal continuum dips near 3 µm by itself).

## What was checked against known science (11 November 2026, live archive)

Reproduce any row with `.venv/bin/python scripts/spectrum.py RA DEC` (or `--comet`).

| Target | Exposures (usable) | What the app reports | What is known |
| --- | --- | --- | --- |
| Field star, 2MASS J = 10.41 (269.59947, +4.93623) | 364 (259) | No bands. Seasons agree within 1.2 %. 123 mJy at 1.64 µm. | 2MASS H = 9.80 is 123.5 mJy. An ordinary star is steady and featureless at this resolution. |
| Field star (269.25728, +4.72168) | 371 (284) | No bands. Seasons agree within 2.6 %. | Same. |
| Comet 3I/ATLAS, IRSA predicted positions | 259 (210) | CO2 gas emission at 4.26 µm in August and December 2025 (about 38× the continuum); CO gas and water vapour emission in December; about 21× brighter in December. | The SPHEREx team reported a CO2-dominated coma in August 2025; the comet passed perihelion in late October 2025. |
| Protostar L1527 (69.97458, +26.05278) | 334 (268) | Water ice (band bottoms out, τ > 2.4), CO2 ice τ = 1.7, CO ice τ = 0.45. | A deeply embedded edge-on protostar with all three ices in earlier infrared spectroscopy. |
| Protostar L1489 IRS (61.17946, +26.31567) | 332 (169) | Water ice τ = 2.3, CO2 ice τ = 1.0; short-wavelength brightness changes between seasons. 90 exposures saturated. | A classic deep-ice protostar seen partly in scattered light. |
| IRAS 04302+2247, DG Tau B | 325 (244), 335 (241) | Water ice in every season. | Edge-on discs with known ice absorption. |
| Starburst galaxy NGC 1614 (68.5001, −8.5791) | 381 (278) | PAH 3.3 µm emission 86 % above the continuum. Steady within 1 %. | A luminous starburst with strong PAH emission. |
| Quasar PG 1634+706 (248.62042, +70.52583) | 513 (408) | No z = 0 bands. Steady within 0.5 %. With the redshift ruler at z = 1.335 the marked Hα, Hβ/[O III], He I, Paβ and Paα lines sit on the five bumps in the spectrum. 2MASS and WISE points lie on it. | Catalogue redshift z = 1.337. |
| Blazars S5 0716+714 and BL Lac | 388 (244), 420 (279) | Variable: 31 % (12σ) and 28 % (8σ) between seasons. | Two of the best-known variable blazars. |
| Barnard's Star, M82 nucleus, HL Tau | — | Mostly "saturated"; no spectrum claimed. | Brighter than about 100 mJy saturates in some or all channels. |

Two false positives appeared during this checking and are now covered by rules and tests: a
background star under the comet imitating a helium line (fixed by medians and the agreement rule),
and the quasar's redshifted Paα in a continuum window imitating CO2 absorption (fixed by the
both-sides rule).

Speed: 25 to 70 s for 330 to 600 exposures on a home connection, most of it the archive query and
the transatlantic reads. Results are cached on disk for six hours
(`.cache/arcadian-spectra-v1`).

## Limits that the interface states

- No aperture correction. Flux in the PSF wings beyond 2.5 px is not added back; agreement with
  2MASS and WISE is within several percent for the sources checked.
- Pixels are 6.15″. Neighbours within about 15″ are blended into the measurement, and the
  background region rotates on the sky with the detector between seasons.
- A forced measurement is not a detection. The panel says so when the median signal-to-noise is
  below 3.
- Band windows are for redshift zero. For galaxies the redshift ruler is manual.
- A star with fast proper motion drifts out of a fixed aperture and can imitate fading.
- Only 3I/ATLAS is supported as a moving target, because IRSA publishes its per-exposure positions.
  No ephemeris is computed here.
- FITS headers and the small windows are parsed in the API process (not in the sandboxed decoder
  used for whole files), from one fixed HTTPS host and validated archive paths only.

## API

- `POST /api/spectrum` with `{"ra": 69.97458, "dec": 26.05278}` or `{"target": "3i-atlas"}`
  (optional `limit`, 20 to 1500 exposures, default 600; larger sets are sampled evenly in time per
  detector). Returns `202 {"id": ...}`.
- `GET /api/spectrum/{id}`: state, progress, every point so far and the current analysis. Poll it.
- `GET /api/spectrum/{id}/csv`: every exposure with its status, and the method as comment lines.
- `GET /api/spectrum/demo/{target}`: the same analysis on the preloaded bundle, offline.
- `GET /api/spectrum/reference?ra=&dec=`: nearest 2MASS and AllWISE photometry within 4″.
- `GET /api/spectrum/features`: band windows, thresholds and the method text.

Settings: `SKYTRACKER_SPECTRUM_WORKERS` (32), `SKYTRACKER_SPECTRUM_MAX_EXPOSURES` (1500),
`SKYTRACKER_SPECTRUM_CACHE_DIR`.

## Where this can go next

1. **Any asteroid or comet.** Per-exposure positions from JPL Horizons (with the spacecraft as
   observer) would give reflectance spectra of thousands of small bodies: hydrated minerals at
   3 µm for planetary defence and resource studies, and volatile activity of comets over time.
2. **Ice maps.** Measuring every pixel of a dark cloud instead of one position maps where water and
   CO2 freeze out: the supply chain for habitable planets.
3. **PSF-weighted photometry** using the PSF/EPSF extension, for crowded fields and a proper
   aperture correction.
4. **Deep-field time series.** Near the ecliptic poles there are tens of thousands of exposures per
   point; the even sampling used now could become a per-wavelength light curve.
5. **A search, not a lookup.** Running the band and variability tests over a catalogue (for example
   every 2MASS source behind a cloud) turns the tool into a survey for icy sightlines and for
   sources that changed.
