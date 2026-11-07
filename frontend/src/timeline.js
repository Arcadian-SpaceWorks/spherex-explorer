/** Chronological frames for the time slider, using archive observation records. */

export function parseUtc(value) {
  if (value == null) return null;
  const text = String(value).trim();
  const parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:[zZ]|[+-]\d{2}:?\d{2})?$/.exec(text);
  if (!parts) return null;
  const [, year, month, day, hour, minute, second] = parts.map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (month < 1 || month > 12 || day < 1 || day > days[month - 1] || hour > 23 || minute > 59 || second > 59) return null;
  const iso = /(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(text) ? text : `${text}Z`;
  const time = Date.parse(iso);
  return Number.isFinite(time) ? time : null;
}

export function formatUtcLabel(value) {
  const time = parseUtc(value);
  if (time == null) return 'Time unavailable';
  return `${new Date(time).toISOString().replace(/Z$/, '')} UTC`;
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
