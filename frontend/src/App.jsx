import DemoTargetSummary from './components/DemoTargetSummary';
import { useRef, useState, useEffect } from 'react';
import SkyMap from './components/SkyMap';
import CoordinatePanel from './components/CoordinatePanel';
import ObservationsTable from './components/ObservationsTable';
import ImageInspector from './components/ImageInspector';
import TemporalImageExplorer from './components/TemporalImageExplorer';
import { demoResult, loadDemoManifest } from './demoAdapter';
import WavelengthFilter from './components/WavelengthFilter';
import { ALL_FILTER, filterParams, filterDemoResult } from './wavelengths';
export default function App() {
  const [mode, setMode] = useState(() => new URLSearchParams(window.location.search).get('mode') === 'demo' ? 'demo' : 'live');
  const [manifest, setManifest] = useState(null), [demoTargetId, setDemoTargetId] = useState('');
  const [filter, setFilter] = useState(ALL_FILTER), [filterError, setFilterError] = useState('');
  const [selected, setSelected] = useState({ra: 210.80227, dec: 54.34895});
  const [navigation, setNavigation] = useState(null), [fov, setFov] = useState(null);
  const [result, setResult] = useState(null), [error, setError] = useState(''), [loading, setLoading] = useState(false);
  const [imageObservation, setImageObservation] = useState(null);
  const request = useRef(null);
  useEffect(() => () => request.current?.abort(), []);
  function chooseDemoTarget(target, scienceNote, activeFilter = ALL_FILTER) {
    const {params} = filterParams(activeFilter);
    const next = filterDemoResult(demoResult(target, scienceNote), params);
    setFilter(activeFilter); setFilterError('');
    setDemoTargetId(target.id); setSelected({ra:target.ra, dec:target.dec}); setNavigation({ra:target.ra, dec:target.dec});
    setResult(next); setError(''); setImageObservation(next.observations[0] || null);
  }
  function changeMode(next) {
    request.current?.abort(); request.current = null;
    setFilter(ALL_FILTER); setFilterError('');
    setMode(next); setResult(null); setError(''); setLoading(false);
    setImageObservation(null); setManifest(null); setFov(null);
  }
  useEffect(() => {
    if (mode !== 'demo') return;
    const controller = new AbortController(); request.current = controller;
    setLoading(true);
    loadDemoManifest({signal:controller.signal}).then(data => {
      if (request.current !== controller) return;
      setManifest(data);
      chooseDemoTarget(data.targets.find(target => target.status === 'ready') || data.targets[0], data.science_note);
    }).catch(err => {if (request.current === controller && !controller.signal.aborted) setError(err.message);})
      .finally(() => {if (request.current === controller) setLoading(false);});
    return () => controller.abort();
  }, [mode]);
  function select(point) {setImageObservation(null); request.current?.abort(); request.current = null; setLoading(false); setSelected(point); setResult(null); setError('');}
  function changeFilter(next, apply) {
    setFilter(next); setFilterError('');
    if (apply && (result || loading || error)) search(next);
  }
  async function search(activeFilter = filter) {
    const {params, error:invalid} = filterParams(activeFilter);
    if (invalid) {setFilterError(invalid); return;}
    setFilterError('');
    if (mode === 'demo') {
      const target = manifest?.targets.find(item => item.id === demoTargetId);
      if (target) chooseDemoTarget(target, manifest.science_note, activeFilter);
      return;
    }
    setImageObservation(null);
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setLoading(true); setResult(null); setError('');
    const timeout = setTimeout(() => controller.abort('timeout'), 65000);
    try {
      const response = await fetch(`/api/observations?${new URLSearchParams({...selected, ...params})}`, {signal: controller.signal});
      const data = await response.json();
      if (!response.ok || data.status !== 'live') throw new Error(data.message || 'The observation service is unavailable.');
      if (request.current === controller) setResult(data);
    } catch (err) {
      if (request.current === controller) setError(controller.signal.aborted ? 'The observation search timed out.' : err.message);
    } finally {clearTimeout(timeout); if (request.current === controller) setLoading(false);}
  }
  return <div className="app"><header><a className="brand" href="/" aria-label="Arcadian SkyTracker home"><span className="brand-icon">✳</span><span>ARCADIAN<span className="brand-sub">SKYTRACKER</span></span></a><div className="header-context">NASA SPACE APPS CHALLENGE 2026 <span>Planet X & SPHEREx · Team prototype</span></div><span className="milestone">02 / FITS EXPLORER</span></header>
    <main>
    <section className="panel mode-panel" aria-label="Data mode">
      <label htmlFor="data-mode">Data mode</label>
      <select id="data-mode" value={mode} onChange={event => changeMode(event.target.value)}>
        <option value="live">Live Mode — query IRSA</option><option value="demo">Demo Mode — preloaded real observations</option>
      </select>
      <p role="note">{mode === 'demo' ? 'DEMO MODE · Local, preloaded real SPHEREx data. No live IRSA query. PNGs are display previews, not scientific arrays.' : 'LIVE MODE · Observation searches and new cutouts require NASA/IPAC IRSA network access.'}</p>
      {mode === 'demo' && <>
        {loading && <p role="status">Loading preloaded target manifest…</p>}
        {manifest && <><label htmlFor="demo-target">Preloaded target</label><select id="demo-target" value={demoTargetId} onChange={event => chooseDemoTarget(manifest.targets.find(target => target.id === event.target.value), manifest.science_note)}>
          {manifest.targets.map(target => <option key={target.id} value={target.id}>{target.name}{target.status === 'missing' ? ' — not prepared' : ''}</option>)}
        </select><form onSubmit={event => {event.preventDefault(); search();}}>
          <WavelengthFilter filter={filter} onChange={changeFilter} error={filterError}/>
          <button type="submit">Apply preloaded filter</button>
        </form>{manifest.targets.find(target => target.id === demoTargetId)?.missing_reason && <p role="status">{manifest.targets.find(target => target.id === demoTargetId).missing_reason}</p>}</>}
      </>}
    </section>
    <div className="intro"><div><div className="eyebrow">EXPLORE THE INFRARED UNIVERSE</div><h1>A point in the sky.<br className="mobile-break"/> A place to begin.</h1><p>Navigate the celestial sphere and discover SPHEREx coverage.</p></div><div className="fov"><span>FIELD OF VIEW</span><strong data-testid="fov">{mode === 'demo' ? 'Preloaded cutouts' : fov ? `${fov[0].toFixed(3)}° × ${fov[1].toFixed(3)}°` : 'Connecting…'}</strong></div></div>
    {mode === 'live' ? <div className="workspace"><section className="map-panel"><div className="map-heading"><span><i/> CELESTIAL ATLAS</span><span>ICRS / DSS2 COLOR</span></div><SkyMap selected={selected} navigation={navigation} onSelect={select} onFov={setFov}/></section><CoordinatePanel selected={selected} onGo={point => {select(point); setNavigation({...point});}} onSearch={() => search()} loading={loading} filter={filter} onFilterChange={changeFilter} filterError={filterError}/></div> : <section className="panel demo-region" aria-label="Preloaded sky region">
      <h2>{manifest?.targets.find(target => target.id === demoTargetId)?.name || 'Preloaded sky region'}</h2>
      <DemoTargetSummary target={manifest?.targets.find(target => target.id === demoTargetId)}/>
      {manifest && <p>Reference ICRS RA {selected.ra.toFixed(6)}°, Dec {selected.dec.toFixed(6)}°. For tracking targets this reference is the first prepared frame; each image records its own center. The cutouts below retain native detector orientation and may have different coverage. Live Mode provides the interactive Aladin sky atlas.</p>}
    </section>}
    <ObservationsTable mode={mode} result={result} loading={loading} error={error} selectedObservation={imageObservation} onViewImage={setImageObservation}/>
    <TemporalImageExplorer result={result} loading={loading} error={error} target={selected}/>
    <ImageInspector observation={imageObservation} target={selected}/></main><footer><span>Arcadian SkyTracker · Milestone 02</span><span>Sky atlas by <a href="https://aladin.cds.unistra.fr/AladinLite/">Aladin Lite / CDS</a> · DSS2 imagery · Observations from <a href="https://irsa.ipac.caltech.edu/Missions/spherex.html">NASA/IPAC IRSA</a></span></footer></div>;
}
