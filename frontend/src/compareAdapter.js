/**
 * Client for POST /api/compare plus small pure helpers. Live rows are sent as IRSA access URLs;
 * Demo Mode rows as the preloaded image ID, which the server reads from the local bundle.
 *
 * The server's decision (ACCEPT / WARN / REJECT and its reasons) is authoritative. The helpers
 * here only pre-select a mode and give early hints; they never decide comparability.
 */
import { parseUtc, usableAccessUrl } from './timeline.js';
import { recordTargetWavelength } from './targetWavelengths.js';

export const COMPARE_SIZE_DEG = 0.3;
export const SIMULTANEOUS_HOURS = 1;
// Same tolerance as the server's time-mode rule (CompareSettings.max_wavelength_delta_um).
export const WAVELENGTH_MATCH_UM = 0.02;
export const MODES = {
  time: {label: 'Time', description: 'Same detector at different dates. A difference image is made only when the wavelengths at the target agree.'},
  wavelength: {label: 'Wavelength', description: 'Different detectors of the same exposure. Shown side by side or blinked, never subtracted.'},
};

export function detectorOf(row) {
  const match = /^SPHEREx-D([1-6])$/.exec(row?.energy_bandpassname || '');
  return match ? Number(match[1]) : null;
}

export function hoursApart(a, b) {
  const ta = parseUtc(a?.observed_at_utc), tb = parseUtc(b?.observed_at_utc);
  return ta == null || tb == null ? null : Math.abs(tb - ta) / 3.6e6;
}

export function sameObservation(a, b) {
  return Boolean(a && b) && a.obs_id === b.obs_id && a.energy_bandpassname === b.energy_bandpassname && a.access_url === b.access_url;
}

export function canPick(row) {
  if (row?.demo) return /^[a-f0-9]{64}$/.test(row.demo.image_id || '');
  return Boolean(row && usableAccessUrl(row.access_url));
}

/** The image reference /api/compare expects for this row. */
export function imageRef(row) {
  return row.demo ? {demo_image_id: row.demo.image_id} : {access_url: row.access_url};
}

/** Wavelength mode for two detectors of one exposure (or within an hour); time mode otherwise. */
export function suggestMode(a, b) {
  if (!a || !b) return 'time';
  const hours = hoursApart(a, b);
  const simultaneous = (a.obs_id && a.obs_id === b.obs_id) || (hours != null && hours <= SIMULTANEOUS_HOURS);
  const differentDetector = detectorOf(a) != null && detectorOf(b) != null && detectorOf(a) !== detectorOf(b);
  return simultaneous && differentDetector ? 'wavelength' : 'time';
}

/** Early, non-authoritative hints shown before the request is sent. */
export function pairHints(a, b, mode) {
  if (!a || !b) return [];
  if (sameObservation(a, b)) return ['A and B are the same observation. Choose a different one.'];
  const hints = [], hours = hoursApart(a, b);
  const da = detectorOf(a), db = detectorOf(b);
  if (mode === 'time') {
    if (da != null && db != null && da !== db) hints.push('Different detectors: a time comparison needs the same detector, so the server will reject it.');
    if (hours != null && hours < SIMULTANEOUS_HOURS) hints.push('Less than an hour apart: too close for a time comparison.');
  } else {
    const simultaneous = (a.obs_id && a.obs_id === b.obs_id) || (hours != null && hours <= SIMULTANEOUS_HOURS);
    if (!simultaneous) hints.push('Not the same exposure: a wavelength comparison needs images taken within an hour of each other.');
    if (da != null && da === db) hints.push('Same detector: a wavelength comparison needs two different detectors.');
  }
  return hints;
}

export function formatSeparation(hours) {
  if (hours == null) return '—';
  if (hours < 1) return `${Math.round(hours * 60)} min`;
  if (hours < 48) return `${hours.toFixed(1)} h`;
  return `${(hours / 24).toFixed(1)} days`;
}

function errorMessage(data, status) {
  if (typeof data?.message === 'string') return data.message;
  if (Array.isArray(data?.detail)) return `The comparison request was refused (${data.detail.map(item => item.msg).join('; ')}).`;
  return status === 503 ? 'The comparison service is busy. Please retry shortly.' : 'The comparison could not be completed.';
}

export async function requestComparison({a, b, target, mode, signal, fetchImpl = fetch}) {
  let response;
  try {
    response = await fetchImpl('/api/compare', {
      method: 'POST', signal, headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({a: imageRef(a), b: imageRef(b),
        ra: target.ra, dec: target.dec, size_deg: COMPARE_SIZE_DEG, mode}),
    });
  } catch (err) {
    if (err?.name === 'AbortError') throw err;
    throw new Error('The comparison service could not be reached.');
  }
  let data = {};
  try {data = await response.json();} catch {data = {};}
  if (!response.ok) throw new Error(errorMessage(data, response.status));
  if (!['ACCEPT', 'WARN', 'REJECT'].includes(data.decision) || !data.previews?.a || !data.previews?.b || data.frames?.length !== 2) {
    throw new Error('The comparison service returned an incomplete result.');
  }
  for (const [row, frame] of [[a, data.frames[0]], [b, data.frames[1]]]) {
    if (row.demo) continue;  // Demo wavelengths come from each preloaded image's own metadata.
    recordTargetWavelength(row, target, Number.isFinite(frame?.wavelength_um)
      ? {status: 'measured', wavelength_um: frame.wavelength_um, bandwidth_um: frame.bandwidth_um ?? null}
      : {status: 'unavailable'});
  }
  return data;
}
