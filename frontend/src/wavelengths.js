// Detector identifiers are not monochromatic wavelength values. Actual product
// coverage comes only from ObsCore em_min/em_max (metres), not a detector lookup.
export const BANDS = Array.from({length:6}, (_, n) => ({band:`SPHEREx-D${n+1}`}));
export const WAVELENGTH_LIMITS = {min:0.7, max:5.1};
export const ALL_FILTER = {band:'', wavelength:''};

export function parseWavelength(text) {
  const trimmed = String(text ?? '').trim();
  if (!trimmed) return {error:'Enter a wavelength in µm.'};
  // Decimal/scientific notation only; no hexadecimal or JavaScript expressions.
  if (!/^[+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:e[+-]?\d+)?$/i.test(trimmed)) return {error:'Enter a finite wavelength in µm.'};
  const value = Number(trimmed.replace(',', '.'));
  if (!Number.isFinite(value) || value < WAVELENGTH_LIMITS.min || value > WAVELENGTH_LIMITS.max) {
    return {error:`Enter a wavelength from ${WAVELENGTH_LIMITS.min} to ${WAVELENGTH_LIMITS.max} µm.`};
  }
  return {value};
}

export function filterParams(filter) {
  if (filter.band) {
    if (!BANDS.some(item => item.band === filter.band)) return {error:'Choose a supported SPHEREx detector.'};
    return {params:{band:filter.band}};
  }
  if (filter.custom || filter.wavelength !== '') {
    const parsed = parseWavelength(filter.wavelength);
    return parsed.error ? {error:parsed.error} : {params:{wavelength_um:String(parsed.value)}};
  }
  return {params:{}};
}

export function filterLabel({band, wavelength_um} = {}) {
  if (band) return `${band} detector only`;
  if (wavelength_um != null) return `product ranges including ${Number(wavelength_um)} µm, plus unknown coverage`;
  return 'all wavelengths';
}

export function wavelengthCoverage(row, wavelengthUm) {
  const low = row.em_min, high = row.em_max;
  if (typeof low !== 'number' || typeof high !== 'number' || !Number.isFinite(low) || !Number.isFinite(high) || low <= 0 || high < low) return 'unknown';
  return low <= wavelengthUm / 1_000_000 && wavelengthUm / 1_000_000 <= high ? 'range_includes' : 'range_excludes';
}

// Apply only to a loaded local demo inventory, never substitute a center-pixel
// wavelength or detector-wide approximation for unavailable spectral bounds.
export function filterDemoResult(result, params) {
  let observations = result.observations.filter(row => !params.band || row.energy_bandpassname === params.band);
  const wavelength_um = params.wavelength_um == null ? null : Number(params.wavelength_um);
  if (wavelength_um != null) observations = observations.map(row => ({...row, wavelength_coverage:wavelengthCoverage(row, wavelength_um)}))
    .filter(row => row.wavelength_coverage !== 'range_excludes');
  return {...result, unfiltered_count:result.observations.length, band:params.band || null, wavelength_um, observations, count:observations.length,
    unknown_wavelength_count:observations.filter(row => row.wavelength_coverage === 'unknown').length};
}
