import { BANDS, WAVELENGTH_LIMITS, parseWavelength } from '../wavelengths';

export default function WavelengthFilter({filter, onChange, error}) {
  const mode = filter.band || (filter.custom || filter.wavelength !== '' ? 'custom' : '');
  const parsed = mode === 'custom' && filter.wavelength !== '' ? parseWavelength(filter.wavelength) : null;
  function choose(value) {
    onChange(value === 'custom' ? {band:'', wavelength:filter.wavelength, custom:true} : {band:value, wavelength:'', custom:false}, value !== 'custom');
  }
  return <div className="wavelength-filter">
    <label htmlFor="wavelength-mode">Wavelength / detector filter</label>
    <select id="wavelength-mode" value={mode} onChange={event => choose(event.target.value)}>
      <option value="">All wavelengths / detectors</option>
      {BANDS.map(item => <option key={item.band} value={item.band}>{item.band} detector</option>)}
      <option value="custom">Specific wavelength…</option>
    </select>
    {mode === 'custom' && <>
      <label htmlFor="wavelength-um">Wavelength in µm <span>{WAVELENGTH_LIMITS.min}–{WAVELENGTH_LIMITS.max}</span></label>
      <input id="wavelength-um" inputMode="decimal" placeholder="e.g. 2.5" value={filter.wavelength}
        aria-invalid={Boolean(error || parsed?.error)} aria-describedby="wavelength-help"
        onChange={event => onChange({band:'', wavelength:event.target.value, custom:true}, false)}/>
    </>}
    <small id="wavelength-help">Filters whole-product spectral ranges, not the wavelength at your exact target. Unknown bounds remain visible. A detector label is not an exact wavelength.</small>
    {(error || parsed?.error) && <p className="error" role="alert">{error || parsed.error}</p>}
  </div>;
}
