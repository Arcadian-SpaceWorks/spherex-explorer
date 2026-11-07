# Verification performed

Date: 2026-11-06. Environment: Fedora Linux, Python 3.14.8, Node 22.22.2, installed Google Chrome in headless mode with WebGL2/SwiftShader.

| Check | Result |
| --- | --- |
| `.venv/bin/python -m pytest backend/tests -q` | 17 passed |
| `npm --prefix frontend test` | Passed |
| `node frontend/tests/coordinates.test.js` | 2 coordinate/click tests passed |
| `npm --prefix frontend run build` | Passed; production assets emitted to `frontend/dist/` |
| `npm --prefix frontend run test:browser` | 3 passed |
| Setup/launch scripts, `bash -n` | Passed |
| npm dependency audit after patch and Aladin installation | 0 vulnerabilities reported |
| Production IRSA `TAP_SCHEMA.columns` query | Confirmed table and required column names/types/units |
| Live FastAPI `/api/observations` at RA 210.80227°, Dec 54.34895° | HTTP 200, `status=live`, 100 records, `truncated=true` |

## What the automated tests exercise

Backend tests cover invalid/missing/nonfinite coordinates, health, successful and zero-row responses, upstream unavailability, ADQL footprint matching/row cap, schema mismatch, malformed and TAP-error responses, truncation, masked/NaN values, time conversion, and network timeout. Backend test observations are explicitly generated fixtures. They are never shipped as an application fallback. The fixture uses FIELD IDs different from names to reproduce the production IRSA VOTable convention.

Chrome tests use the real locally bundled Aladin Lite 3.8.1 JavaScript and WebAssembly. They verify canvas initialization; a real pointer click and ICRS projection; the selected marker's catalog coordinates; Go To Coordinates and resulting map center; wheel zoom and field-of-view update; drag pan without changing the selection; actual DSS2 JPEG tile downloads from the documented STScI mirror; and a mobile-width unavailable-service state without horizontal page overflow. Click projection comparison allows pixel rounding in pointer handling; displayed coordinates retain six decimal places.

The third browser test uses actual Vite and Uvicorn servers. It clicks Search SPHEREx Observations, reaches live IRSA through the Vite proxy and FastAPI, requires HTTP 200 and `status=live`, checks a nonempty table with the returned row count and first observation ID, and captures a screenshot. This is a network-dependent integration check, separate from deterministic unit tests.

## Observed limitations and warnings

- Initial checks exposed and fixed the Vite JSX configuration and Astropy FIELD-ID/name parsing. The official CDN timed out; the final implementation bundles the official pinned npm release locally.
- CDS's tile hosts were unreachable here. IRSA's DSS2 mirror responded to curl but did not send browser CORS headers. The final map uses the CORS-enabled STScI mirror published in the official CDS registry. A real sky rendered during the successful live-search browser run; no static substitute was used.
- Starlette emits one TestClient deprecation warning for `httpx`; tests pass.
- Vite reports a large optional Aladin chunk (~2.39 MB uncompressed, ~840 KB gzip), containing the sky engine and WebAssembly. The application imports it dynamically. Build succeeds.
- Browser verification covers installed headless Chrome and a simulated mobile viewport. Firefox, physical mobile devices, and production hosting were not tested. Real upstream services can be unavailable later; the UI reports failures and never invents observations.

Browser screenshots are generated under ignored `frontend/test-results/` when the integration tests run. `dashboard.png` captures interaction state; `live-observations.png` captures actual survey imagery and live observation results.
