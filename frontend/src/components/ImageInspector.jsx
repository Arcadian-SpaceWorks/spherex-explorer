import { useEffect, useRef, useState } from 'react';

const number = (value, digits = 5) => value == null ? '—' : Number(value).toFixed(digits);
const CUTOUT_DEG = 0.3;  // width of the quick cutout around the selected target
const wait = (ms, signal) => new Promise((resolve, reject) => {
  const id = setTimeout(resolve, ms);
  signal.addEventListener('abort', () => {clearTimeout(id); reject(new DOMException('Aborted', 'AbortError'));}, {once: true});
});
const wavelength = spectral => spectral ? `${number(spectral.wavelength_um)} µm · bandwidth ${number(spectral.bandwidth_um)} µm (approx.)` : 'Unavailable for this pixel';

function ImageCanvas({metadata, onPixel}) {
  const [zoom, setZoom] = useState(1), [pan, setPan] = useState({x:0,y:0});
  const [loaded, setLoaded] = useState(false), [failed, setFailed] = useState(false);
  const svg = useRef(null), group = useRef(null), drag = useRef(null);
  const {width, height, target} = metadata;
  function point(event, element) {
    return new DOMPoint(event.clientX, event.clientY).matrixTransform(element.getScreenCTM().inverse());
  }
  function down(event) {
    if (event.button !== 0) return;
    const start = point(event, svg.current);
    drag.current = {start, pan, clientX:event.clientX, clientY:event.clientY, moved:false};
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function move(event) {
    if (!drag.current) return;
    const current = point(event, svg.current);
    if (Math.hypot(event.clientX-drag.current.clientX,event.clientY-drag.current.clientY) > 4) drag.current.moved = true;
    if (drag.current.moved) setPan({x:drag.current.pan.x + current.x-drag.current.start.x, y:drag.current.pan.y + current.y-drag.current.start.y});
  }
  function up(event) {
    if (!drag.current) return;
    const clicked = !drag.current.moved;
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (clicked && loaded && !failed) {
      const p = point(event, group.current);
      const x = Math.floor(p.x), y = height - 1 - Math.floor(p.y);
      if (x >= 0 && x < width && y >= 0 && y < height) onPixel(x, y);
    }
  }
  function reset() {setZoom(1); setPan({x:0,y:0});}
  function shift(x,y) {setPan(previous => ({x:previous.x + x*width*.12, y:previous.y + y*height*.12}));}
  return <div className="image-viewer">
    <div className="image-controls" aria-label="Image navigation controls">
      <button type="button" onClick={() => setZoom(z => Math.min(16,z*1.4))} aria-label="Zoom in image">+</button>
      <button type="button" onClick={() => setZoom(z => Math.max(.25,z/1.4))} aria-label="Zoom out image">−</button>
      <button type="button" onClick={reset}>Fit image</button>
      <span data-testid="image-zoom">{Math.round(zoom*100)}%</span>
      <button type="button" onClick={() => shift(-1,0)} aria-label="Pan image left">←</button>
      <button type="button" onClick={() => shift(1,0)} aria-label="Pan image right">→</button>
      <button type="button" onClick={() => shift(0,-1)} aria-label="Pan image up">↑</button>
      <button type="button" onClick={() => shift(0,1)} aria-label="Pan image down">↓</button>
    </div>
    <div className="fits-viewport">
      {!loaded && !failed && <p className="image-loading" role="status">Loading science preview…</p>}
      {failed && <p className="image-loading error" role="alert">Preview unavailable or evicted from cache. Reload this image below.</p>}
      <svg ref={svg} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="SPHEREx science image in native detector orientation" data-testid="fits-canvas"
        onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={() => {drag.current=null;}}>
        <g ref={group} transform={`translate(${pan.x} ${pan.y}) translate(${width/2} ${height/2}) scale(${zoom}) translate(${-width/2} ${-height/2})`}>
          <image href={metadata.preview_url} width={width} height={height} onLoad={() => setLoaded(true)} onError={() => setFailed(true)} />
          {loaded && target?.status === 'inside' && <g transform={`translate(${target.x+.5} ${height-target.y-.5})`} stroke="#80e7ce" strokeWidth="2" data-testid="fits-target">
            <path d={`M ${-width/80/zoom} 0 H ${width/80/zoom} M 0 ${-width/80/zoom} V ${width/80/zoom}`} vectorEffect="non-scaling-stroke"/>
          </g>}
        </g>
      </svg>
    </div>
    <p className="result-note">Drag to pan; use + / − to zoom. Click a pixel for its value, sky coordinates and wavelength. Checkerboard indicates masked pixels.</p>
  </div>;
}

export default function ImageInspector({observation, target}) {
  const [metadata, setMetadata] = useState(null), [error, setError] = useState('');
  const [loading, setLoading] = useState(false), [retry, setRetry] = useState(0);
  const [full, setFull] = useState(false);  // false: quick IRSA cutout; true: whole detector image
  const [pixel, setPixel] = useState(null), [pixelError, setPixelError] = useState(''), [pixelLoading, setPixelLoading] = useState(false);
  const pixelRequest = useRef(null);
  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    setMetadata(null); setError(''); setPixel(null); setPixelError(''); setPixelLoading(false);
    setLoading(Boolean(observation));
    pixelRequest.current?.abort();
    if (!observation) return () => controller.abort();
    const timeout = setTimeout(() => controller.abort(), full ? 720000 : 150000);
    async function load() {
      try {
        const body = {access_url:observation.access_url, ra:target.ra, dec:target.dec, ...(full ? {} : {cutout_deg:CUTOUT_DEG})};
        let data;
        for (let attempt = 0; ; attempt++) {
          const response = await fetch('/api/images', {method:'POST', headers:{'Content-Type':'application/json'}, signal:controller.signal, body:JSON.stringify(body)});
          data = await response.json();
          if (response.ok) break;
          // The server handles one file at a time; wait a few seconds and try again instead of failing.
          if (data.code === 'viewer_busy' && attempt < 4) {await wait(4000, controller.signal); continue;}
          throw new Error(data.message || 'This FITS image could not be loaded.');
        }
        if (!cancelled) setMetadata(data);
      } catch (err) {
        if (!cancelled) setError(controller.signal.aborted ? 'Image request timed out. The file may be large; please retry.' : err.message);
      } finally {clearTimeout(timeout); if (!cancelled) setLoading(false);}
    }
    load();
    return () => {cancelled=true; clearTimeout(timeout); controller.abort(); pixelRequest.current?.abort();};
  }, [observation, target.ra, target.dec, retry, full]);

  async function inspectPixel(x,y) {
    pixelRequest.current?.abort();
    const controller = new AbortController(); pixelRequest.current=controller;
    setPixel(null); setPixelError(''); setPixelLoading(true);
    try {
      const response = await fetch(`/api/images/${metadata.image_id}/pixel?${new URLSearchParams({x,y})}`, {signal:controller.signal});
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || 'Pixel readout unavailable.');
      if (pixelRequest.current === controller) setPixel(data);
    } catch (err) {if (!controller.signal.aborted) setPixelError(err.message);}
    finally {if (pixelRequest.current === controller) setPixelLoading(false);}
  }
  return <section className="panel image-inspector" aria-busy={loading} aria-label="FITS image inspector">
    <div className="section-heading"><div><div className="eyebrow">SPHEREx SCIENCE IMAGE</div><h2>FITS image inspector</h2></div><span className={`tag ${metadata ? 'live' : ''}`}>{loading ? 'Downloading FITS' : error ? 'Unavailable' : metadata ? metadata.cache_hit ? 'Cached IRSA file' : 'IRSA file' : 'Select an observation'}</span></div>
    {!observation ? <p className="empty">Choose View Image on an observation to inspect its original science image.</p> : <>
      <p className="result-note">Selected observation {observation.obs_id} · {observation.energy_bandpassname} · {observation.obs_collection}</p>
      <div className="image-mode" role="group" aria-label="Image size">
        <button type="button" className={full ? 'secondary' : ''} aria-pressed={!full} onClick={() => setFull(false)}>Quick cutout ({CUTOUT_DEG}° around target)</button>
        <button type="button" className={full ? '' : 'secondary'} aria-pressed={full} onClick={() => setFull(true)}>Full detector image (slow)</button>
      </div>
      {loading && <p className="empty" role="status">{full ? 'Downloading and inspecting the original FITS from IRSA. Full detector images can be tens of megabytes; this may take a few minutes.' : 'Downloading and inspecting a small cutout around your target from IRSA. This usually takes 20 to 30 seconds.'}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {metadata && <>
        <div className="image-facts">
          <div><span>Observation ID</span><strong>{metadata.observation_id || observation.obs_id || '—'}</strong></div>
          <div><span>UTC {metadata.observed_at_utc ? '(FITS)' : '(archive)'}</span><strong>{metadata.observed_at_utc || observation.observed_at_utc || '—'}</strong></div>
          <div><span>Detector</span><strong>{metadata.detector ?? observation.energy_bandpassname ?? '—'}</strong></div>
          <div><span>Science extension</span><strong>HDU {metadata.science_hdu} · IMAGE · {metadata.width} × {metadata.height}</strong></div>
          <div><span>Archive wavelength bounds</span><strong>{number(observation.em_min == null ? null : observation.em_min*1e6,3)} – {number(observation.em_max == null ? null : observation.em_max*1e6,3)} µm</strong></div>
          <div><span>Wavelength at image center</span><strong>{wavelength(metadata.center.spectral)}</strong></div>
        </div>
        <p className="image-science-note">{metadata.cutout ? `IRSA cutout, ${metadata.cutout.size_deg}° wide, centred on your selected target. ${metadata.orientation}` : `${metadata.orientation} The full detector image is shown without recentering on your selected target.`}</p>
        {metadata.cutout && <p className="result-note">Source: IRSA image-server cutout of {metadata.fits_url}</p>}
        <p className="result-note">{metadata.target?.status === 'inside' ? `Mint cross: target mapped through the FITS WCS at pixel x=${number(metadata.target.x,2)}, y=${number(metadata.target.y,2)}.` : metadata.target?.status === 'outside' ? 'Your selected target falls outside this science image according to its WCS; no target marker is drawn.' : 'Target placement unavailable: this file has no usable celestial WCS.'}</p>
        <ImageCanvas key={`${metadata.image_id}-${retry}`} metadata={metadata} onPixel={inspectPixel}/>
        <div className="pixel-readout" aria-live="polite">{pixelLoading ? 'Reading pixel…' : pixelError ? pixelError : pixel ? <>
          <span>Pixel ({pixel.x}, {pixel.y})</span><span>{pixel.value == null ? 'Invalid value' : `${number(pixel.value,6)} ${metadata.unit || ''}`}{pixel.masked ? ' · masked in preview' : ''}</span><span>ICRS {number(pixel.ra,6)}°, {number(pixel.dec,6)}°</span><span>λ {wavelength(pixel.spectral)}</span><span>FLAGS: {pixel.flags ?? 'unavailable'}</span>
        </> : 'Click the image to inspect a science pixel.'}</div>
        <p className="image-science-note">{metadata.wavelength_note}</p>
        <p className="result-note">Display only: asinh stretch (a={metadata.scaling.asinh_a}), {metadata.scaling.percentiles.join('–')}th percentiles, limits {number(metadata.scaling.low,6)} to {number(metadata.scaling.high,6)} {metadata.unit || ''}. {metadata.scaling.constant ? 'Constant image shown in neutral gray. ' : ''}{metadata.scaling.masked_pixels.toLocaleString()} pixels masked. {metadata.scaling.mask_policy} Preview {metadata.preview_width} × {metadata.preview_height}, nearest-neighbor sampling. Original FITS values are unchanged.</p>
        {metadata.notes.map(note => <p className="result-note" key={note}>{note}</p>)}
        <div className="image-actions"><a className="download-fits" href={metadata.original_url} target="_blank" rel="noreferrer">{metadata.cutout ? 'Download FITS cutout' : 'Download original FITS'} ↗ ({(metadata.bytes/1024/1024).toFixed(metadata.bytes < 1048576 ? 2 : 1)} MiB)</a><span className="result-note">If the local cache expires, reload this image.</span></div>
        <details><summary>FITS HDUs and WCS metadata</summary><div className="table-scroll"><table><thead><tr><th>HDU</th><th>Extension</th><th>Type</th><th>Array shape / columns</th></tr></thead><tbody>{metadata.hdus.map(hdu => <tr key={hdu.index}><td>{hdu.index}</td><td>{hdu.name}</td><td>{hdu.type}</td><td>{hdu.shape?.join(' × ') || hdu.columns?.join(', ') || 'No image array'}</td></tr>)}</tbody></table></div><p className="result-note">Spatial WCS: {metadata.spatial_wcs} · Spectral WCS: {metadata.spectral_wcs}. Complete headers and lookup tables remain in the downloadable original.</p><pre>{metadata.science_header}</pre>{metadata.wavelength_header && <pre>{metadata.wavelength_header}</pre>}</details>
      </>}
      {!loading && <button type="button" className="secondary reload-image" onClick={() => setRetry(n => n+1)}>{error ? 'Retry image' : 'Reload image'}</button>}
    </>}
  </section>;
}
