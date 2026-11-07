import { useEffect, useRef, useState } from 'react';
import { loadAladin } from '../aladin';
import { selectedFromClick } from '../coordinates';
export default function SkyMap({ selected, navigation, onSelect, onFov }) {
  const host = useRef(null), api = useRef(null), catalog = useRef(null), A = useRef(null);
  const callbacks = useRef({onSelect, onFov});
  callbacks.current = {onSelect, onFov};
  const [status, setStatus] = useState('loading');
  const [surveyError, setSurveyError] = useState(false);
  const latest = useRef({selected, navigation});
  latest.current = {selected, navigation};
  useEffect(() => {
    let cancelled = false;
    loadAladin().then(a => {
      if (cancelled) return;
      A.current = a;
      const survey = a.HiPS('https://stpubdata.s3.us-east-1.amazonaws.com/mast/skybackgrounds/DSSColor');
      survey.query.catch(() => {if (!cancelled) setSurveyError(true);});
      const map = a.aladin(host.current, {survey, target: '210.80227 54.34895', fov: 12,
        cooFrame: 'ICRSd', mode: 'dark', backgroundColor: 'rgb(5, 10, 18)', showReticle: false, showCooGridControl: true, showFullscreenControl: true, showProjectionControl: false});
      api.current = map;
      // Local development probe used by browser integration tests.
      if (import.meta.env.DEV) host.current.skyAtlas = map;
      catalog.current = a.catalog({name: 'Selected location', sourceSize: 22, color: '#66e6c4', shape: 'cross'});
      map.addCatalog(catalog.current);
      catalog.current.addSources([a.source(latest.current.selected.ra, latest.current.selected.dec)]);
      if (latest.current.navigation) map.gotoRaDec(latest.current.navigation.ra, latest.current.navigation.dec);
      map.on('click', event => {const point = selectedFromClick(event); if (point) callbacks.current.onSelect(point);});
      const updateFov = () => callbacks.current.onFov(map.getFov());
      map.on('zoomChanged', updateFov);
      map.on('resizeChanged', updateFov);
      updateFov();
      setStatus('ready');
    }).catch(() => {if (!cancelled) setStatus('error');});
    return () => {
      cancelled = true;
      // Aladin Lite 3.8.1 replaces callbacks through on(); it has no off() API.
      for (const event of ['click', 'zoomChanged', 'resizeChanged']) api.current?.on(event, null);
      if (host.current) {delete host.current.skyAtlas; host.current.replaceChildren();}
      api.current = null;
    };
  }, []);
  useEffect(() => {
    if (!catalog.current) return;
    catalog.current.removeAll();
    catalog.current.addSources([A.current.source(selected.ra, selected.dec)]);
  }, [selected]);
  useEffect(() => {if (navigation && api.current) api.current.gotoRaDec(navigation.ra, navigation.dec);}, [navigation]);
  return <div className="map-shell">
    <div ref={host} className="sky-map" data-testid="sky-map" aria-label="Interactive Aladin Lite celestial map"/>
    {status !== 'ready' && <div className="map-status" role="status">{status === 'loading' ? 'Connecting to Aladin Lite…' : 'Sky map unavailable. Check your connection and WebGL support, then reload.'}</div>}
    {surveyError && <div className="map-status" role="status">DSS2 imagery unavailable. Coordinates and navigation remain usable; check your connection and reload.</div>}
    <div className="map-caption">DSS2 · Optical sky survey · Network tiles <span>Drag to explore · Scroll to zoom · Click to select</span></div>
  </div>;
}
