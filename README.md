# Arcadian SkyTracker

**Explore a Changing Universe**

Arcadian SkyTracker is an interactive astronomical exploration platform developed by **Arcadian SpaceWorks** for the **NASA Space Apps Challenge**. It helps visitors find real NASA SPHEREx infrared observations, browse them over time, compare images, and understand what the available data can—and cannot—show.

## Project overview

NASA's SPHEREx mission surveys the sky in infrared light. Its open observations are valuable, but FITS images, sky coordinates, detector metadata, and changing wavelengths can be difficult to explore without specialist software. Arcadian SkyTracker puts those observations into a visual workflow for learning and preliminary investigation.

### The problem

- Astronomical FITS files and their metadata are unfamiliar to many visitors.
- Finding observations of the same sky region at different times takes several steps.
- Images can look different because of wavelength, calibration, or image processing rather than a changing object.

### Our solution: Explore → Compare → Understand

1. **Explore:** choose a point on the sky or a curated target, then browse available observations.
2. **Compare:** select two real images or move through them with the Time Slider.
3. **Understand:** inspect dates, image differences, compatibility checks, and a plain-English explanation of the evidence and its limits.

The platform is intended for students and educators, astronomy enthusiasts and citizen scientists, and researchers doing an initial look at SPHEREx data. It is an exploration tool, not a discovery confirmation pipeline.

## Features

| Feature | What it does |
| --- | --- |
| Interactive sky map | Uses Aladin Lite and a DSS2 optical sky background to select ICRS coordinates in Live Mode. |
| Live SPHEREx search | Queries NASA/IPAC IRSA for observations covering a selected sky position; filters by detector or archive wavelength bounds. |
| FITS image inspector | Opens bounded SPHEREx cutouts, shows a display preview, and provides pixel, WCS, and available spectral readouts. Original FITS bytes remain available to download. |
| Time Slider | Browses observations by actual UTC time, with playback and on-demand comparison of suitable epochs. |
| Image Comparison | Displays real Before and After images, and a signed difference image only when the comparison checks allow one. It explains why a visual difference may be scientifically uncertain. |
| Offline Demo Mode | Bundles 60 real SPHEREx FITS cutouts and previews across M101, M31, Barnard's Star, and 3I/ATLAS. Search, playback, and comparison of these files do not require IRSA. |
| 3I/ATLAS views | Shows fixed-sky and prediction-centered views. Dashed cyan rings mark official predicted positions. Local image checks report nearby excesses without identifying them as comet detections. |
| Bounded processing | Uses local caches, limited downloads, checksum checks for bundled data, and an isolated FITS processing worker. |

The scientific change-detection code includes conservative eligibility checks. Current real-observation results do **not** establish an astrophysical discovery, verified comet motion, or calibrated comet brightening. A separate synthetic validation tool exists behind a developer flag and is not part of the normal visitor workflow.

## Technology and architecture

The frontend uses **React 19**, **Vite 6**, and **Aladin Lite 3.8.1**. The backend uses **Python**, **FastAPI**, **Astropy**, **NumPy**, **SciPy**, **reproject**, and **Pillow** for archive access, FITS/WCS processing, comparison, and previews. Dependencies are pinned in [frontend/package.json](frontend/package.json), [frontend/package-lock.json](frontend/package-lock.json), and [backend/requirements.txt](backend/requirements.txt).

~~~mermaid
flowchart LR
    U[Visitor] --> F[React / Vite frontend]
    F --> B[FastAPI backend]
    B --> I[NASA/IPAC IRSA<br/>Live Mode]
    F --> D[Bundled demo manifest<br/>and previews]
    B --> A[Bundled original FITS<br/>Demo Mode analysis]
~~~

Vite proxies requests beginning with /api to FastAPI. Demo previews and the manifest are served locally; FITS readouts and comparisons still use the backend. There is no database or user account service.

## Getting started

### Prerequisites

- **Python 3.12 or newer** with the standard venv module. The setup script checks this requirement.
- **Node.js and npm.** Node.js 22 is the version used for current local development; the pinned Vite package declares support for Node 18, 20, and 22 or newer.
- A modern browser. Live sky-map viewing needs WebGL and network access.
- Free local ports **8000** (API) and **5173** (frontend), unless you configure different ports for the one-command launcher.

On Linux or macOS, clone and install from the repository root:

~~~bash
git clone https://github.com/Arcadian-SpaceWorks/spherex-explorer.git
cd spherex-explorer
./scripts/setup.sh
~~~

The setup script creates a local .venv, installs the pinned Python packages, and runs npm ci for the frontend. No environment variables or external services are required for the bundled Demo Mode. Installation itself needs access to the Python and npm package registries.

### Start the application

On Linux, or on macOS with **Bash 4.3 or newer**, the recommended one-terminal launcher is:

~~~bash
./scripts/start.sh
~~~

It starts both servers, installs dependencies first if they are missing, and stops its own processes on Ctrl+C. It exits if either configured port is already occupied. For different ports:

~~~bash
SKYTRACKER_BACKEND_PORT=8010 SKYTRACKER_FRONTEND_PORT=5180 ./scripts/start.sh
~~~

macOS's default Bash is older than the launcher's required Bash version. On macOS, or if you prefer two terminals, use the scripts below after setup:

~~~bash
# Terminal 1, from the repository root
./scripts/backend.sh
~~~

~~~bash
# Terminal 2, from the repository root
./scripts/frontend.sh
~~~

Open **http://127.0.0.1:5173/** for the app and **http://127.0.0.1:8000/docs** for the API documentation. To open directly in Demo Mode, use **http://127.0.0.1:5173/?mode=demo**. The two-terminal scripts use fixed default ports; the one-terminal launcher supports the port variables above. The frontend proxy follows the launcher-selected API port.

The equivalent manual commands, after setup, are:

~~~bash
# Terminal 1, repository root
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
~~~

~~~bash
# Terminal 2, repository root
npm --prefix frontend run dev
~~~

Useful optional settings include SKYTRACKER_FITS_CACHE_DIR for the downloaded FITS cache, SKYTRACKER_FITS_MAX_BYTES for its per-file size limit, and SKYTRACKER_DEMO_DIR to point the backend at another validated demo bundle. The defaults work for the bundled data. See [backend/app/image_download.py](backend/app/image_download.py), [backend/app/compare_service.py](backend/app/compare_service.py), and [backend/app/demo.py](backend/app/demo.py) for the complete configuration and limits.

## Demo Mode

Open the demo URL above or choose **Demo Mode** in the app. Select **M101** (3 frames), **M31** (18), **Barnard's Star** (21), or **3I/ATLAS** (18). These are preserved real SPHEREx observations with checksummed FITS, preview, and metadata files.

Use the Time Slider to browse actual UTC acquisition times or press Play. To compare, choose **A** and **B** in the observation table and press **Find Changes** in the existing comparison panel. The panel shows the real images and an explanation; it enables the Difference view only when its compatibility checks permit one. Expand **How did we reach this conclusion?** for observation IDs, wavelength and quality information, and processing limits.

The bundled target list, previews, FITS analysis, and comparison run without IRSA access. **Keep both local servers running** for FITS readouts, registered tracking views, and comparisons. The live Aladin sky map is shown in Live Mode and loads external sky-survey tiles; Demo Mode uses its local target view instead.

Validate the bundled data before a presentation:

~~~bash
.venv/bin/python scripts/prepare_demo.py --validate frontend/public/demo
~~~

See [Demo architecture](docs/demo-architecture.md) and [target provenance](docs/demo-target-showcase.md).

## Live Mode

Choose **Live Mode**, click the Aladin map or enter RA and Dec, then select **Search SPHEREx Observations**. The backend queries NASA/IPAC IRSA for actual observation metadata. Filter the results by detector or archive wavelength bounds, open an observation in the FITS viewer, or select two rows for comparison.

Live Mode needs access to **IRSA** for searches and FITS cutouts and to the external sky-survey service for Aladin's background tiles. New images can take time to download and process; repeated requests may use the local cache. The inspector requests a small cutout by default and offers an explicit full-detector option. Search and image retrieval have bounded time and size limits; an unavailable archive returns an error rather than invented observations.

Same-detector images can still represent different wavelengths at the selected position. A difference preview or an accepted visual comparison does not by itself establish physical variability. Scientific screening stays unavailable when essential calibration, spectral, registration, PSF, or uncertainty evidence is missing.

## Example: explore 3I/ATLAS

1. Open **http://127.0.0.1:5173/?mode=demo** and select **3I/ATLAS**.
2. Move the Time Slider through its 18 real observations from 14 December 2025. The dates are actual exposure times.
3. Switch between **Fixed sky** and **Follow predicted comet**. Cyan dashed rings show positions from the verified IRSA prediction table. The scientific details describe local image checks near those positions.
4. Select two observations as A and B, press **Find Changes**, and read the result and expandable scientific details.

The bundled sequence has 12 exposure IDs and 13 exact UTC timestamps across about 3.33 hours. The official predicted separation between its first and last positions is about 581.80 arcseconds. Image checks find local excesses near some predictions, but do not establish their identity or calibrated positional uncertainty. The app therefore does not report verified comet motion. See [comet analysis and limitations](docs/comet-integration.md).

## Scientific integrity

SPHEREx uses infrared filters whose effective wavelength changes across an image. Images from different wavelengths may show different structures even if the sky has not changed. Alignment, background, calibration, image sharpness (PSF), quality flags, and uncertainty all affect a comparison.

The app distinguishes **what the pixels show**, **what observation metadata predict**, and **what scientific evidence supports**. It can display visual residuals while blocking unsupported astronomical change claims. Its controlled synthetic tests validate software behavior only; they are not observations or discoveries. Read the [real-observation assessment](docs/final-real-analysis.md) and [scientific change-detection notes](docs/scientific-change-detection.md) for the current evidence and limits.

## Tests and build

Run these commands from the repository root after setup:

~~~bash
.venv/bin/python -m pytest backend/tests -q
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:browser
~~~

Backend tests and most browser tests use mocked network responses or labeled synthetic fixtures. The standard Playwright suite also includes a live IRSA metadata search and map checks that need network access. Its live FITS download tests are **opt-in** with SKYTRACKER_LIVE_FITS=1 and can transfer real archive data; leave that setting unset for routine checks.

Playwright starts its own test servers on ports **8001** and **5174**. Its configuration expects Chrome at /usr/bin/google-chrome by default; set CHROME_PATH to an absolute Chrome executable path on another system. For focused local-data browser checks without an archive query:

~~~bash
npm --prefix frontend run test:browser -- tests/browser/demo.spec.js tests/browser/comet-tracking.spec.js
~~~

The developer-only synthetic validation UI is hidden by default and can be enabled with VITE_ENABLE_DETECTION_LAB=true when starting Vite. Its results must never be presented as real astronomical detections.

## Project structure

~~~text
backend/
  app/                 FastAPI routes, IRSA client, FITS service, comparison and analysis
  tests/               API, image, science and regression tests
  requirements.txt     Pinned Python dependencies
frontend/
  src/                 React application and Aladin integration
  public/demo/         Bundled real observations, manifest, previews and FITS
  tests/               Unit and Playwright browser tests
  package.json         Frontend scripts and dependencies
scripts/               Setup, launch and data-validation utilities
demo/discovery/         Bundled target-discovery metadata and ephemeris table
docs/                   Scientific provenance, validation and architecture notes
~~~

## Team and credits

**Arcadian SpaceWorks** developed this project for the NASA Space Apps Challenge. Verified Git commit authors include **PantelisZeritis, AndrewMpel, Andreas Belias, and Danae**; the commit history records contributions without assigning unverified roles.

SPHEREx data and archive services come from **NASA/IPAC IRSA**. The sky atlas uses **Aladin Lite** from CDS and its external survey imagery. We acknowledge NASA Space Apps and the open-source projects named in the dependency manifests. This is an independent team project and does not imply NASA endorsement.

## Future roadmap

- Calibrated multi-epoch change detection with stronger wavelength, PSF and uncertainty evidence.
- Moving-object tracking that can associate sources across frames and measure positional uncertainty.
- Additional astronomy missions and datasets.
- Scientifically supported light curves and spectral analysis.
- More guided educational and citizen-science experiences.

These are proposed improvements, not current detection claims.

## License

This repository currently has **no LICENSE file**. No open-source license terms have been specified by the project maintainers.
