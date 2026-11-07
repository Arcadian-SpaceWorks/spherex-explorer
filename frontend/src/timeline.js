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

/**
 * Parse boundary date strings (e.g. YYYY-MM-DD from date inputs) to UTC epoch ms.
 * When isEnd=true and format is YYYY-MM-DD, encompasses the full end-of-day (23:59:59.999Z).
 */
export function parseBoundaryDate(value, isEnd = false) {
  if (value == null) return null;
  const text = String(value).trim();
  if (!text) return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    const iso = isEnd ? `${text}T23:59:59.999Z` : `${text}T00:00:00.000Z`;
    const time = Date.parse(iso);
    return Number.isFinite(time) ? time : null;
  }
  const time = parseUtc(text) ?? Date.parse(text);
  return Number.isFinite(time) ? time : null;
}

/**
 * Convert user-specified cadence period value and unit into milliseconds.
 * Supports hours, days, weeks, months, years. Returns 0 if disabled/invalid.
 */
export function parsePeriodMs(value, unit = 'days') {
  const num = Number(value);
  if (!Number.isFinite(num) || num <= 0) return 0;
  switch (unit) {
    case 'hours': return Math.round(num * 3600 * 1000);
    case 'days': return Math.round(num * 86400 * 1000);
    case 'weeks': return Math.round(num * 7 * 86400 * 1000);
    case 'months': return Math.round(num * 30.4375 * 86400 * 1000);
    case 'years': return Math.round(num * 365.25 * 86400 * 1000);
    default: return Math.round(num * 86400 * 1000);
  }
}

/**
 * Filter and sample chronological frames by date window [startDate, endDate]
 * and minimum time cadence periodMs.
 */
export function filterTimelineFrames(frames, options = {}) {
  const { startDate, endDate, periodMs = 0 } = options;
  const startMs = parseBoundaryDate(startDate, false);
  const endMs = parseBoundaryDate(endDate, true);
  const isDateFiltered = startMs != null || endMs != null;
  const isPeriodFiltered = Number.isFinite(periodMs) && periodMs > 0;

  if (!isDateFiltered && !isPeriodFiltered) {
    return {
      frames: frames || [],
      totalArchiveFrames: (frames || []).length,
      isFiltered: false,
    };
  }

  // 1. Date window filtering
  const inWindow = (frames || []).filter(frame => {
    const time = parseUtc(frame.observed_at_utc);
    if (time == null) {
      return !isDateFiltered && !isPeriodFiltered;
    }
    if (startMs != null && time < startMs) return false;
    if (endMs != null && time > endMs) return false;
    return true;
  });

  // 2. Period / cadence sampling (greedy minimum interval)
  if (!isPeriodFiltered || inWindow.length <= 1) {
    return {
      frames: inWindow,
      totalArchiveFrames: (frames || []).length,
      isFiltered: true,
    };
  }

  const sampled = [];
  let nextThreshold = -Infinity;

  for (const frame of inWindow) {
    const time = parseUtc(frame.observed_at_utc);
    if (time == null) continue;
    if (time >= nextThreshold) {
      sampled.push(frame);
      nextThreshold = time + periodMs;
    }
  }

  return {
    frames: sampled,
    totalArchiveFrames: (frames || []).length,
    isFiltered: true,
  };
}
