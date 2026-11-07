/** Chronological frames for the time slider, using archive observation records. */

export function parseUtc(value) {
  if (value == null) return null;
  const text = String(value).trim();
  if (!text) return null;
  const iso = /(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(text) ? text : `${text}Z`;
  const time = Date.parse(iso);
  return Number.isFinite(time) ? time : null;
}

export function formatUtcLabel(value) {
  if (parseUtc(value) == null) return 'Time unavailable';
  const text = String(value).trim();
  return /utc$/i.test(text) ? text : `${text} UTC`;
}

export function usableAccessUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch {
    return null;
  }
}

export function wavelengthLabel(observation) {
  const min = observation?.em_min;
  const max = observation?.em_max;
  if (min == null && max == null) return 'Wavelength bounds unavailable';
  const microns = value => value == null || !Number.isFinite(Number(value)) ? '—' : (Number(value) * 1e6).toFixed(3);
  return `${microns(min)} – ${microns(max)} µm`;
}

export function isSyntheticObservation(observation, metadata) {
  const text = [observation?.obs_id, observation?.obs_collection, metadata?.observation_id]
    .filter(value => value != null && String(value).trim() !== '')
    .join(' ');
  return /synthetic|fixture|test-only|demo/i.test(text);
}

function identity(observation) {
  return `${observation?.obs_id ?? ''}\0${observation?.energy_bandpassname ?? ''}`;
}

/**
 * One slider step per observation that has an http(s) image link.
 * Steps follow real timestamps. Missing timestamps sort after dated frames.
 * Equal timestamps stay in obs_id / bandpass order and do not invent extra steps.
 */
export function chronologicalFrames(observations) {
  const skipped = [];
  const usable = [];
  for (const observation of observations || []) {
    if (!usableAccessUrl(observation?.access_url)) skipped.push(observation);
    else usable.push(observation);
  }
  const frames = usable.sort((a, b) => {
    const left = parseUtc(a.observed_at_utc);
    const right = parseUtc(b.observed_at_utc);
    if (left == null && right == null) return identity(a).localeCompare(identity(b));
    if (left == null) return 1;
    if (right == null) return -1;
    if (left !== right) return left - right;
    return identity(a).localeCompare(identity(b));
  });
  return {
    frames,
    skippedCount: skipped.length,
    undatedCount: frames.filter(frame => parseUtc(frame.observed_at_utc) == null).length,
  };
}
