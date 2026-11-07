// SPHEREx detector wavelength ranges in µm, from IRSA spherex.obscore em_min/em_max
// (checked 2026-11-07). Neighbouring detectors overlap slightly at their edges.
export const BANDS = [
  {band: 'SPHEREx-D1', min: 0.75, max: 1.12},
  {band: 'SPHEREx-D2', min: 1.10, max: 1.65},
  {band: 'SPHEREx-D3', min: 1.63, max: 2.43},
  {band: 'SPHEREx-D4', min: 2.40, max: 3.85},
  {band: 'SPHEREx-D5', min: 3.81, max: 4.43},
  {band: 'SPHEREx-D6', min: 4.41, max: 5.01},
];
// Must match WAVELENGTH_MIN_UM / WAVELENGTH_MAX_UM in backend/app/irsa.py.
export const WAVELENGTH_LIMITS = {min: 0.7, max: 5.1};
export const ALL_FILTER = {band: '', wavelength: ''};

export const bandRange = band => BANDS.find(item => item.band === band);
export const bandsForWavelength = um => BANDS.filter(item => um >= item.min && um <= item.max).map(item => item.band);

/** Returns {value} for a usable wavelength in µm, or {error} explaining why not. */
export function parseWavelength(text) {
  const trimmed = String(text ?? '').trim();
  if (!trimmed) return {error: 'Enter a wavelength in µm.'};
  const value = Number(trimmed.replace(',', '.'));
  if (!Number.isFinite(value) || value < WAVELENGTH_LIMITS.min || value > WAVELENGTH_LIMITS.max) {
    return {error: `Enter a wavelength from ${WAVELENGTH_LIMITS.min} to ${WAVELENGTH_LIMITS.max} µm.`};
  }
  return {value};
}

/** Query parameters for GET /api/observations, or {error} if the filter is incomplete. */
export function filterParams(filter) {
  if (filter.band) return {params: {band: filter.band}};
  if (filter.custom || filter.wavelength !== '') {
    const parsed = parseWavelength(filter.wavelength);
    return parsed.error ? {error: parsed.error} : {params: {wavelength_um: String(parsed.value)}};
  }
  return {params: {}};
}

/** Short human label for the filter a result was searched with. */
export function filterLabel({band, wavelength_um} = {}) {
  if (band) {
    const range = bandRange(band);
    return range ? `${band} only (${range.min.toFixed(2)}–${range.max.toFixed(2)} µm)` : `${band} only`;
  }
  if (wavelength_um != null) return `images covering ${Number(wavelength_um)} µm`;
  return 'all wavelengths';
}
