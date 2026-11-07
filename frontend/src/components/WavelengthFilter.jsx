import { BANDS, WAVELENGTH_LIMITS, bandsForWavelength, parseWavelength } from '../wavelengths';

const CUSTOM = 'custom';

export default function WavelengthFilter({filter, onChange, error}) {
  const mode = filter.band || (filter.wavelength !== '' || filter.custom ? CUSTOM : '');
  const parsed = mode === CUSTOM && filter.wavelength !== '' ? parseWavelength(filter.wavelength) : null;
  const detectors = parsed?.value != null ? bandsForWavelength(parsed.value) : [];
  function choose(value) {
    if (value === CUSTOM) onChange({band: '', wavelength: filter.wavelength, custom: true}, false);
    else onChange({band: value, wavelength: '', custom: false}, true);
  }
  return <div className="wavelength-filter">
    <label htmlFor="wavelength-mode">Wavelength <span>loads only matching images</span></label>
    <select id="wavelength-mode" value={mode} onChange={event => choose(event.target.value)}>
      <option value="">All wavelengths (0.75–5.0 µm)</option>
      {BANDS.map(item => <option key={item.band} value={item.band}>{item.band.replace('SPHEREx-', '')} · {item.min.toFixed(2)}–{item.max.toFixed(2)} µm</option>)}
      <option value={CUSTOM}>Specific wavelength…</option>
    </select>
    {mode === CUSTOM && <>
      <label htmlFor="wavelength-um">Wavelength in µm <span>{WAVELENGTH_LIMITS.min}–{WAVELENGTH_LIMITS.max}</span></label>
      <input id="wavelength-um" type="text" inputMode="decimal" placeholder="e.g. 2.5" value={filter.wavelength}
        aria-invalid={Boolean(error || parsed?.error)} aria-describedby="wavelength-help"
        onChange={event => onChange({band: '', wavelength: event.target.value, custom: true}, false)}/>
      <small id="wavelength-help">{parsed?.error ? '' : detectors.length ? `Covered by ${detectors.map(name => name.replace('SPHEREx-', '')).join(' and ')}. Press Search to load those images.` : 'Shows only images whose wavelength range includes this value.'}</small>
    </>}
    {(error || parsed?.error) && <p className="error" role="alert">{error || parsed.error}</p>}
  </div>;
}
