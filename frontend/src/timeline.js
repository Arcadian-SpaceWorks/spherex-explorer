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

export function formatMonthDate(value) {
  const time = parseUtc(value);
  if (time == null) return 'Date unavailable';
  const d = new Date(time);
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${months[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
}

export function formatMonthYear(value) {
  const time = parseUtc(value);
  if (time == null) return 'Unknown month';
  const d = new Date(time);
  const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  return `${months[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
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
 * Generate formatted file name for downloaded timelapse video.
 */
export function timelapseFilename(selectedMonthKey = 'all', target = null) {
  const monthTag = selectedMonthKey && selectedMonthKey !== 'all' ? selectedMonthKey : 'all-months';
  const ra = target?.ra != null && Number.isFinite(Number(target.ra)) ? `ra${Number(target.ra).toFixed(2)}` : '';
  const dec = target?.dec != null && Number.isFinite(Number(target.dec)) ? `dec${Number(target.dec).toFixed(2)}` : '';
  const coordTag = ra && dec ? `_${ra}_${dec}` : '';
  return `spherex_timelapse_${monthTag}${coordTag}.webm`;
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
 * Extract all unique Months & Years where pictures were actually taken.
 */
export function extractAvailableMonths(frames) {
  const list = [];
  const map = new Map();
  const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

  for (let i = 0; i < (frames || []).length; i++) {
    const frame = frames[i];
    const time = parseUtc(frame.observed_at_utc);
    if (time == null) continue;
    const d = new Date(time);
    const year = d.getUTCFullYear();
    const month = d.getUTCMonth();
    const key = `${year}-${String(month + 1).padStart(2, '0')}`;
    const label = `${months[month]} ${year}`;
    const shortLabel = `${months[month].slice(0, 3)} ${year}`;

    if (!map.has(key)) {
      const item = {
        key,
        year,
        month,
        label,
        shortLabel,
        count: 0,
        firstDate: frame.observed_at_utc.slice(0, 10),
        lastDate: frame.observed_at_utc.slice(0, 10),
        firstFrameIndex: i,
      };
      map.set(key, item);
      list.push(item);
    }
    const entry = map.get(key);
    entry.count += 1;
    if (frame.observed_at_utc) entry.lastDate = frame.observed_at_utc.slice(0, 10);
  }
  return list;
}

/**
 * Group chronological frames by Month & Year for organized date navigation.
 */
export function groupFramesByMonth(frames) {
  const groups = [];
  const map = new Map();

  for (let i = 0; i < (frames || []).length; i++) {
    const frame = frames[i];
    const time = parseUtc(frame.observed_at_utc);
    let key = 'Undated';
    let label = 'Undated';
    let year = 0;
    let month = 0;

    if (time != null) {
      const d = new Date(time);
      year = d.getUTCFullYear();
      month = d.getUTCMonth();
      key = `${year}-${String(month + 1).padStart(2, '0')}`;
      const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
      label = `${months[month]} ${year}`;
    }

    if (!map.has(key)) {
      const entry = { key, label, year, month, firstIndex: i, frames: [] };
      map.set(key, entry);
      groups.push(entry);
    }
    map.get(key).frames.push(frame);
  }

  return groups;
}

/**
 * Parse boundary date (YYYY-MM-DD) to UTC epoch ms.
 * - when isEnd=false: defaults to start of day 00:00:00.000 UTC
 * - when isEnd=true: defaults to end of day 23:59:59.999 UTC
 * Backwards compatible if optional time string is provided.
 */
export function parseBoundaryDate(dateStr, timeOrIsEnd = false, maybeIsEnd = false) {
  if (dateStr == null) return null;
  const d = String(dateStr).trim();
  if (!d) return null;

  let timeStr = '';
  let isEnd = false;
  if (typeof timeOrIsEnd === 'boolean') {
    isEnd = timeOrIsEnd;
  } else {
    timeStr = timeOrIsEnd != null ? String(timeOrIsEnd).trim() : '';
    isEnd = Boolean(maybeIsEnd);
  }

  if (/^\d{4}-\d{2}-\d{2}$/.test(d)) {
    let timePart = isEnd ? '23:59:59.999' : '00:00:00.000';
    if (timeStr) {
      const match = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(timeStr);
      if (match) {
        const hh = match[1].padStart(2, '0');
        const mm = match[2].padStart(2, '0');
        const ss = (match[3] || (isEnd ? '59' : '00')).padStart(2, '0');
        timePart = `${hh}:${mm}:${ss}.${isEnd ? '999' : '000'}`;
      }
    }
    const iso = `${d}T${timePart}Z`;
    const time = Date.parse(iso);
    return Number.isFinite(time) ? time : null;
  }

  const time = parseUtc(d) ?? Date.parse(d);
  return Number.isFinite(time) ? time : null;
}

/**
 * Convert user-specified cadence period value and unit into milliseconds.
 * Supports months, days, weeks, years. Returns 0 if disabled/invalid.
 */
export function parsePeriodMs(value, unit = 'months') {
  const num = Number(value);
  if (!Number.isFinite(num) || num <= 0) return 0;
  switch (unit) {
    case 'hours': return Math.round(num * 3600 * 1000);
    case 'days': return Math.round(num * 86400 * 1000);
    case 'weeks': return Math.round(num * 7 * 86400 * 1000);
    case 'months': return Math.round(num * 30.4375 * 86400 * 1000);
    case 'years': return Math.round(num * 365.25 * 86400 * 1000);
    default: return Math.round(num * 30.4375 * 86400 * 1000);
  }
}

/**
 * Filter and sample chronological frames by:
 * 1. Selected Month & Year (where pictures were taken, e.g. '2026-05' or 'all')
 * 2. Or Date window [startDate, endDate]
 * 3. Optional survey cadence interval (e.g. 6 months survey cadence, 1 month, 1 day).
 */
export function filterTimelineFrames(frames, options = {}) {
  const {
    selectedMonthKey = 'all',
    startMonthKey = '',
    endMonthKey = '',
    startDate,
    startTime = '',
    endDate,
    endTime = '',
    enableCadence = false,
    cadenceValue = 6,
    cadenceUnit = 'months',
  } = options;

  const isMonthSelected = selectedMonthKey && selectedMonthKey !== 'all';
  const isMonthRange = Boolean(startMonthKey || endMonthKey);
  const startMs = parseBoundaryDate(startDate, startTime, false);
  const endMs = parseBoundaryDate(endDate, endTime, true);
  const isDateFiltered = startMs != null || endMs != null;
  const isCadenceActive = Boolean(enableCadence) && Number(cadenceValue) > 0;

  if (!isMonthSelected && !isMonthRange && !isDateFiltered && !isCadenceActive) {
    return {
      frames: frames || [],
      totalArchiveFrames: (frames || []).length,
      isFiltered: false,
    };
  }

  // 1. Month / Date filtering
  const inWindow = (frames || []).filter(frame => {
    const time = parseUtc(frame.observed_at_utc);
    if (time == null) {
      return !isMonthSelected && !isMonthRange && !isDateFiltered && !isCadenceActive;
    }

    const monthKey = frame.observed_at_utc ? frame.observed_at_utc.slice(0, 7) : '';

    // Specific Month & Year filter
    if (isMonthSelected && monthKey !== selectedMonthKey) {
      return false;
    }

    // Month range filter
    if (startMonthKey && monthKey < startMonthKey) return false;
    if (endMonthKey && monthKey > endMonthKey) return false;

    // Date boundary filter
    if (startMs != null && time < startMs) return false;
    if (endMs != null && time > endMs) return false;

    return true;
  });

  // 2. Cadence sampling
  if (!isCadenceActive || inWindow.length <= 1) {
    return {
      frames: inWindow,
      totalArchiveFrames: (frames || []).length,
      isFiltered: isMonthSelected || isMonthRange || isDateFiltered || isCadenceActive,
    };
  }

  const val = Number(cadenceValue) || 1;
  const sampled = [];

  if (cadenceUnit === 'months') {
    let nextAllowedMonthIndex = -Infinity;
    for (const frame of inWindow) {
      const time = parseUtc(frame.observed_at_utc);
      if (time == null) continue;
      const d = new Date(time);
      const monthIndex = d.getUTCFullYear() * 12 + d.getUTCMonth();
      if (monthIndex >= nextAllowedMonthIndex) {
        sampled.push(frame);
        nextAllowedMonthIndex = monthIndex + val;
      }
    }
  } else if (cadenceUnit === 'years') {
    let nextAllowedYear = -Infinity;
    for (const frame of inWindow) {
      const time = parseUtc(frame.observed_at_utc);
      if (time == null) continue;
      const year = new Date(time).getUTCFullYear();
      if (year >= nextAllowedYear) {
        sampled.push(frame);
        nextAllowedYear = year + val;
      }
    }
  } else if (cadenceUnit === 'days' || cadenceUnit === 'weeks') {
    const dayStep = cadenceUnit === 'weeks' ? val * 7 : val;
    let nextAllowedDayIndex = -Infinity;

    for (const frame of inWindow) {
      const time = parseUtc(frame.observed_at_utc);
      if (time == null) continue;
      const dayIndex = Math.floor(time / 86400000);
      if (dayIndex >= nextAllowedDayIndex) {
        sampled.push(frame);
        nextAllowedDayIndex = dayIndex + dayStep;
      }
    }
  } else {
    const stepHours = val;
    let nextAllowedHourIndex = -Infinity;

    for (const frame of inWindow) {
      const time = parseUtc(frame.observed_at_utc);
      if (time == null) continue;
      const hourIndex = Math.floor(time / 3600000);
      if (hourIndex >= nextAllowedHourIndex) {
        sampled.push(frame);
        nextAllowedHourIndex = hourIndex + stepHours;
      }
    }
  }

  return {
    frames: sampled,
    totalArchiveFrames: (frames || []).length,
    isFiltered: true,
  };
}
