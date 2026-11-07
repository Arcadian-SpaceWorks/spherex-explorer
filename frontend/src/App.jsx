import { useCallback, useRef, useState, useEffect } from 'react';
import SkyMap from './components/SkyMap';
import CoordinatePanel from './components/CoordinatePanel';
import ObservationsTable from './components/ObservationsTable';
import ImageInspector from './components/ImageInspector';
import TemporalImageExplorer from './components/TemporalImageExplorer';
import { ALL_FILTER, filterParams } from './wavelengths';
export default function App() {
  const [selected, setSelected] = useState({ra: 210.80227, dec: 54.34895});
  const [navigation, setNavigation] = useState(null), [fov, setFov] = useState(null);
  const [result, setResult] = useState(null), [error, setError] = useState(''), [loading, setLoading] = useState(false);
  const [imageObservation, setImageObservation] = useState(null);
  const [imageBusy, setImageBusy] = useState(false), [pendingObservation, setPendingObservation] = useState(null);
  const onImageBusy = useCallback(busy => {setImageBusy(busy); if (!busy) setPendingObservation(null);}, []);
  // While an image is still downloading, picking another row asks first instead of silently cancelling it.
  function viewImage(row) {
    if (row === imageObservation) return;
    if (imageBusy) setPendingObservation(row); else setImageObservation(row);
  }
  function resolvePending(confirmed) {if (confirmed && pendingObservation) setImageObservation(pendingObservation); setPendingObservation(null);}
  const [filter, setFilter] = useState(ALL_FILTER), [filterError, setFilterError] = useState('');
  const request = useRef(null);
  // A preset choice re-runs an existing search at once; a typed wavelength waits for Search / Enter.
  function changeFilter(next, apply) {
    setFilter(next); setFilterError('');
    if (apply && (result || loading || error)) search(next);
  }
  useEffect(() => () => request.current?.abort(), []);
  function select(point) {setImageObservation(null); setPendingObservation(null); request.current?.abort(); request.current = null; setLoading(false); setSelected(point); setResult(null); setError('');}
  async function search(activeFilter = filter) {
    const {params, error: invalid} = filterParams(activeFilter);
    if (invalid) {setFilterError(invalid); return;}
    setFilterError('');
    setImageObservation(null); setPendingObservation(null);
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setLoading(true); setResult(null); setError('');
    const timeout = setTimeout(() => controller.abort('timeout'), 65000);
    try {
      const response = await fetch(`/api/observations?${new URLSearchParams({ra: selected.ra, dec: selected.dec, ...params})}`, {signal: controller.signal});
      const data = await response.json();
      if (!response.ok || data.status !== 'live') throw new Error(data.message || 'The observation service is unavailable.');
      if (request.current === controller) setResult(data);
    } catch (err) {
      if (request.current === controller) setError(controller.signal.aborted ? 'The observation search timed out.' : err.message);
    } finally {clearTimeout(timeout); if (request.current === controller) setLoading(false);}
  }
  return <div className="app"><header><a className="brand" href="/" aria-label="Arcadian SkyTracker home"><span className="brand-icon">✳</span><span>ARCADIAN<span className="brand-sub">SKYTRACKER</span></span></a><div className="header-context">NASA SPACE APPS CHALLENGE 2026 <span>Planet X & SPHEREx · Team prototype</span></div><span className="milestone">02 / FITS EXPLORER</span></header>
    <main><div className="intro"><div><div className="eyebrow">EXPLORE THE INFRARED UNIVERSE</div><h1>A point in the sky.<br className="mobile-break"/> A place to begin.</h1><p>Navigate the celestial sphere and discover SPHEREx coverage.</p></div><div className="fov"><span>FIELD OF VIEW</span><strong data-testid="fov">{fov ? `${fov[0].toFixed(3)}° × ${fov[1].toFixed(3)}°` : 'Connecting…'}</strong></div></div>
    <div className="workspace"><section className="map-panel"><div className="map-heading"><span><i/> CELESTIAL ATLAS</span><span>ICRS / DSS2 COLOR</span></div><SkyMap selected={selected} navigation={navigation} onSelect={select} onFov={setFov}/></section><CoordinatePanel selected={selected} onGo={point => {select(point); setNavigation({...point});}} onSearch={() => search()} loading={loading} filter={filter} onFilterChange={changeFilter} filterError={filterError}/></div>
    <ObservationsTable result={result} loading={loading} error={error} selectedObservation={imageObservation} imageBusy={imageBusy} onViewImage={viewImage}/>
    <TemporalImageExplorer result={result} loading={loading} error={error} target={selected}/>
    <ImageInspector observation={imageObservation} target={selected} pendingObservation={pendingObservation} onResolvePending={resolvePending} onBusyChange={onImageBusy}/></main><footer><span>Arcadian SkyTracker · Milestone 02</span><span>Sky atlas by <a href="https://aladin.cds.unistra.fr/AladinLite/">Aladin Lite / CDS</a> · DSS2 imagery · Observations from <a href="https://irsa.ipac.caltech.edu/Missions/spherex.html">NASA/IPAC IRSA</a></span></footer></div>;
}
