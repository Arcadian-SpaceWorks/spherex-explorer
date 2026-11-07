import { useEffect, useState } from 'react';
import { validCoordinates } from '../coordinates';
import WavelengthFilter from './WavelengthFilter';
export default function CoordinatePanel({selected, onGo, onSearch, loading, filter, onFilterChange, filterError}) {
  const [ra, setRa] = useState(String(selected.ra)), [dec, setDec] = useState(String(selected.dec));
  const [error, setError] = useState('');
  useEffect(() => {setRa(selected.ra.toFixed(6)); setDec(selected.dec.toFixed(6)); setError('');}, [selected]);
  function go(event) {
    event.preventDefault();
    if (!validCoordinates(ra, dec)) {setError('Enter RA from 0 to <360° and Dec from −90 to +90°.'); return;}
    setError(''); onGo({ra: Number(ra), dec: Number(dec)});
  }
  return <aside className="panel coordinates">
    <div className="eyebrow">TARGET INSPECTOR</div><h2>Selected location</h2>
    <span className="tag">ICRS · decimal degrees</span>
    <dl><div><dt>Right ascension</dt><dd data-testid="selected-ra">{selected.ra.toFixed(6)}<small>°</small></dd></div><div><dt>Declination</dt><dd data-testid="selected-dec">{selected.dec.toFixed(6)}<small>°</small></dd></div></dl>
    <form onSubmit={go}><label htmlFor="ra">RA <span>0 ≤ RA &lt; 360°</span></label><input id="ra" inputMode="decimal" value={ra} onChange={e => setRa(e.target.value)} required/>
      <label htmlFor="dec">Dec <span>−90° to +90°</span></label><input id="dec" inputMode="decimal" value={dec} onChange={e => setDec(e.target.value)} required/>
      {error && <p className="error" role="alert">{error}</p>}<button className="secondary" type="submit">Go To Coordinates <span>↗</span></button></form>
    <div className="search-block"><div className="eyebrow">SPHEREx ARCHIVE</div><p>Find spectral images whose footprints cover your selected point.</p>
      <form onSubmit={event => {event.preventDefault(); if (!loading) onSearch();}}>
        <WavelengthFilter filter={filter} onChange={onFilterChange} error={filterError}/>
        <button type="submit" disabled={loading}>{loading ? 'Searching IRSA…' : 'Search SPHEREx Observations'}</button>
      </form><small>Live query · NASA/IPAC IRSA</small></div>
  </aside>;
}
