import { loadDemoImage } from './demoAdapter.js';
import { recordFromMetadata } from './targetWavelengths.js';

/**
 * FITS viewer integration contract
 *
 * The time slider does not decode FITS files. It asks the existing image
 * service for a prepared preview, then displays that preview for the
 * archive observation currently selected on the slider.
 *
 * Request: POST /api/images
 * Body: { access_url: string, ra: number, dec: number, cutout_deg: number }
 *   access_url, obs_id, observed_at_utc, energy_bandpassname, obs_collection,
 *   em_min and em_max come from GET /api/observations (IRSA spherex.obscore).
 *   ra and dec are the selected ICRS target already stored by the app.
 *
 * Success JSON used by the slider:
 *   preview_url, observation_id, observed_at_utc, detector,
 *   center.spectral.wavelength_um, center.spectral.bandwidth_um,
 *   wavelength_note
 * Pixel readout, WCS placement, stretch, and original-file download stay in
 * ImageInspector. The slider only reads preview_url.
 *
 * A frame with no http(s) access_url is omitted. A failed prepare, a missing
 * preview_url, or a preview that fails to load is an error for that step;
 * the other steps stay selectable. Do not substitute a synthetic image in
 * the live UI. Test fixtures must use observation ids or collections that
 * match synthetic|fixture|test-only|demo so the slider can label them.
 */

export const CUTOUT_DEG = 0.3;

export async function loadObservationImage(observation, target, options = {}) {
  const data = await prepareObservationImage(observation, target, options);
  // Every prepared image reports the wavelength at the target; keep it for the results table.
  recordFromMetadata(observation, target, data);
  return data;
}

async function prepareObservationImage(observation, target, {signal, fetchImpl = fetch, full = false, client = 'time-slider'} = {}) {
  if (observation.demo) return loadDemoImage(observation, {signal, fetchImpl});
  let response;
  try {
    response = await fetchImpl('/api/images', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-SkyTracker-Client': client,
      },
      signal,
      body: JSON.stringify({
        access_url: observation.access_url,
        ra: target.ra,
        dec: target.dec,
        ...(full ? {} : {cutout_deg: CUTOUT_DEG}),
      }),
    });
  } catch (err) {
    if (err?.name === 'AbortError') throw err;
    throw new Error('The image service could not be reached.');
  }
  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  if (!response.ok) throw new Error(data.message || 'This observation image could not be loaded.');
  if (!data.preview_url) throw new Error('The image service returned no preview for this observation.');
  return data;
}
