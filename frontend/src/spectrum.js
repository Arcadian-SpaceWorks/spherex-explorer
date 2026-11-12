// Pure helpers for the spectrum view: API calls, plot scales, season series and rest-frame lines.

export const WAVELENGTH_RANGE = [0.7, 5.1];
// Nominal band edges of the six SPHEREx detectors, micrometres (for orientation only).
export const DETECTOR_BANDS = [[1, 0.75, 1.11], [2, 1.11, 1.64], [3, 1.64, 2.42], [4, 2.42, 3.82], [5, 3.82, 4.42], [6, 4.42, 5.0]];
// Validated on the app's dark surface with the dataviz palette checker (all pairs, colour-vision safe).
export const SEASON_COLORS = ['#3987e5', '#d95926', '#199e70'];
export const OTHER_COLOR = '#8b96a8';
export const SEASON_SHAPES = ['circle', 'square', 'triangle'];

// Rest wavelengths (micrometres) of lines that are bright in galaxies and quasars.
export const REST_LINES = [
  ['[O II]', 0.3728], ['Hβ', 0.4863], ['[O III]', 0.5008], ['Hα', 0.6565], ['[S III]', 0.9533],
  ['He I', 1.0833], ['Paβ', 1.2822], ['Paα', 1.8756], ['PAH', 3.29], ['Brα', 4.0523],
];

export function redshiftedLines(z, range = WAVELENGTH_RANGE) {
  if (!Number.isFinite(z) || z < 0) return [];
  return REST_LINES.map(([label, rest]) => ({label, rest, observed: rest * (1 + z)}))
    .filter(line => line.observed >= range[0] && line.observed <= range[1]);
}

export const usablePoints = points => (points || []).filter(point => point.status === 'ok' && Number.isFinite(point.wavelength_um) && Number.isFinite(point.flux_mjy));

/* Seasons get the three validated colours, newest first in importance: with more than three
   seasons the oldest are folded into one neutral "earlier" series rather than inventing hues. */
export function seasonSeries(seasons) {
  const list = seasons || [];
  const shown = list.slice(-SEASON_COLORS.length);
  const folded = list.slice(0, list.length - shown.length);
  const series = shown.map((season, slot) => ({key: `s${season.index}`, indexes: [season.index], color: SEASON_COLORS[slot],
    shape: SEASON_SHAPES[slot], label: seasonLabel(season), measured: season.measured}));
  if (folded.length) {
    series.unshift({key: 'earlier', indexes: folded.map(season => season.index), color: OTHER_COLOR, shape: 'diamond',
      label: `${folded.length} earlier season${folded.length > 1 ? 's' : ''} (${folded[0].start_utc.slice(0, 7)} to ${folded.at(-1).end_utc.slice(0, 7)})`,
      measured: folded.reduce((sum, season) => sum + season.measured, 0)});
  }
  return series;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export function shortDate(utc) {
  if (!utc) return '—';
  const [year, month, day] = utc.slice(0, 10).split('-').map(Number);
  return `${day} ${MONTHS[month - 1]} ${year}`;
}
export function seasonLabel(season) {
  const start = shortDate(season.start_utc), end = shortDate(season.end_utc);
  return start === end ? start : `${start} – ${end}`;
}

export function percentile(sorted, fraction) {
  if (!sorted.length) return NaN;
  const position = (sorted.length - 1) * fraction, low = Math.floor(position);
  return sorted[low] + (sorted[Math.min(low + 1, sorted.length - 1)] - sorted[low]) * (position - low);
}

/* Flux axis limits. Linear: from zero (or the lowest point when negative) to just above the data,
   so one outlier does not flatten everything else. Log: positive points only. */
export function fluxDomain(points, log) {
  const values = points.map(point => point.flux_mjy).filter(Number.isFinite).sort((a, b) => a - b);
  if (!values.length) return log ? [0.1, 10] : [0, 1];
  if (log) {
    const positive = values.filter(value => value > 0);
    if (!positive.length) return [0.1, 10];
    const low = Math.max(percentile(positive, 0.02) / 1.6, positive.at(-1) / 1e5), high = positive.at(-1) * 1.5;
    return [low, Math.max(high, low * 10)];
  }
  const high = values.at(-1), low = Math.min(0, values[0]);
  const span = high - low || Math.abs(high) || 1;
  return [low < 0 ? low - span * 0.05 : 0, high + span * 0.08];
}

/* True when the brightest points are more than 25 times the typical one. */
export function wideRange(points) {
  const values = points.map(point => point.flux_mjy).filter(value => value > 0).sort((a, b) => a - b);
  return values.length >= 5 && values.at(-1) > 25 * percentile(values, 0.5);
}

export function niceTicks([low, high], count = 5) {
  const span = high - low;
  if (!(span > 0)) return [low];
  const raw = span / count, power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map(factor => factor * power).find(candidate => candidate >= raw);
  const ticks = [];
  for (let value = Math.ceil(low / step) * step; value <= high + step * 1e-9; value += step) ticks.push(Number(value.toPrecision(12)));
  return ticks;
}

export function logTicks([low, high]) {
  const ticks = [];
  for (let power = Math.floor(Math.log10(low)); power <= Math.ceil(Math.log10(high)); power += 1) {
    const value = 10 ** power;
    if (value >= low && value <= high) ticks.push(value);
  }
  return ticks;
}

export function formatFlux(value) {
  if (!Number.isFinite(value)) return '—';
  const size = Math.abs(value);
  if (size >= 1000) return `${(value / 1000).toPrecision(3)} Jy`;
  if (size >= 100) return `${value.toFixed(0)} mJy`;
  if (size >= 1) return `${value.toPrecision(3)} mJy`;
  if (size >= 0.001) return `${(value * 1000).toPrecision(3)} µJy`;
  return `${value.toExponential(1)} mJy`;
}

export function formatTick(value) {
  const size = Math.abs(value);
  if (size === 0) return '0';
  if (size >= 1000) return `${value / 1000}k`;
  return size >= 1 ? String(Number(value.toPrecision(3))) : String(Number(value.toPrecision(2)));
}

/* One short sentence per detected band, in plain words. */
export function describeFeature(result, feature) {
  const percent = result.strength == null ? null : Math.round(result.strength * 100);
  if (result.kind === 'absorption') {
    const depth = result.optical_depth == null ? '' : result.optical_depth_is_lower_limit
      ? ` (the band bottoms out: optical depth above ${result.optical_depth.toFixed(1)})` : ` (optical depth ${result.optical_depth.toFixed(2)})`;
    return `${Math.min(percent, 100)}% of the light is absorbed at ${feature.center} µm${depth}.`;
  }
  if (percent == null) return `Emission at ${feature.center} µm on a continuum too faint to measure.`;
  return percent >= 100 ? `${(1 + result.strength).toFixed(1)}× the continuum at ${feature.center} µm.`
    : `${percent}% above the continuum at ${feature.center} µm.`;
}

export function outcomeSummary(counts = {}) {
  const names = {saturated: 'saturated', flagged: 'flagged pixels', edge: 'too close to the detector edge', outside: 'off the detector',
    no_background: 'no clean background', unavailable: 'file unavailable', unreadable: 'file unreadable', invalid: 'invalid value', no_wavelength: 'no wavelength'};
  return Object.entries(counts).filter(([status, count]) => status !== 'ok' && count > 0)
    .sort((a, b) => b[1] - a[1]).map(([status, count]) => `${count} ${names[status] || status}`);
}

async function json(response) {
  let data = {};
  try {data = await response.json();} catch {data = {};}
  if (!response.ok) throw new Error(data.message || (response.status >= 500
    ? 'The app\'s backend is not responding. Start it with ./scripts/start.sh.' : 'The spectrum service refused the request.'));
  return data;
}

export async function startSpectrum(body, {signal} = {}) {
  return (await json(await fetch('/api/spectrum', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body), signal}))).id;
}
export const fetchSpectrum = async (id, {signal} = {}) => json(await fetch(`/api/spectrum/${id}`, {signal}));
export const fetchDemoSpectrum = async (target, {signal} = {}) => json(await fetch(`/api/spectrum/demo/${target}`, {signal}));
export const fetchFeatures = async ({signal} = {}) => json(await fetch('/api/spectrum/features', {signal}));
export const fetchReference = async ({ra, dec}, {signal} = {}) => json(await fetch(`/api/spectrum/reference?${new URLSearchParams({ra, dec})}`, {signal}));
