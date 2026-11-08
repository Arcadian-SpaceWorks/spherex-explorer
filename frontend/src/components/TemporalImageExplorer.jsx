import ComparePanel, {ComparisonResult} from './ComparePanel';
import {previousEpoch} from '../compareAdapter';
import { useEffect, useMemo, useRef, useState } from 'react';
import { chronologicalFrames, parseUtc, formatUtcLabel, isSyntheticObservation, wavelengthLabel } from '../timeline';
import { loadObservationImage } from '../imageAdapter';
import TimeSlider from './TimeSlider';
import { CAVEATS, exportProblem, recordTimelapse, timelapseFilename } from '../timelapse';
import DownloadProgress, { useElapsed } from './DownloadProgress';

// Playback shows each frame this long once its image has loaded (live frames can take a minute).
export const PLAY_DWELL_MS = 1500;

function TimelapseExport({frames, target, mode}) {
  const [state, setState] = useState({status: 'idle'});
  const request = useRef(null);
  const problem = exportProblem(frames);
  useEffect(() => () => {request.current?.abort(); if (state.url) URL.revokeObjectURL(state.url);}, [state.url]);
  async function run() {
    const controller = new AbortController(); request.current = controller;
    if (state.url) URL.revokeObjectURL(state.url);
    setState({status: 'running', progress: 0, total: frames.length});
    try {
      const blob = await recordTimelapse({frames, target, mode, signal: controller.signal,
        loadImage: (frame, options) => loadObservationImage(frame, target, options),
        onProgress: (progress, total) => setState({status: 'running', progress, total})});
      const url = URL.createObjectURL(blob), name = timelapseFilename(target);
      setState({status: 'done', url, name, bytes: blob.size});
      const link = document.createElement('a'); link.href = url; link.download = name; link.click();
    } catch (err) {
      setState(err?.name === 'AbortError' ? {status: 'idle'} : {status: 'error', message: err.message || 'The video could not be recorded.'});
    }
  }
  return <div className="timelapse-export" data-testid="timelapse-export">
    {state.status === 'running'
      ? <div role="status">Preparing frame {state.progress} of {state.total} (live frames may need a download)…
          <button type="button" className="secondary" onClick={() => request.current?.abort()}>Cancel export</button></div>
      : <button type="button" className="secondary" onClick={run} disabled={Boolean(problem)}>Export time-lapse video</button>}
    {problem && state.status !== 'running' && <p className="result-note">{problem}</p>}
    {state.status === 'done' && <p className="result-note">Saved <a href={state.url} download={state.name} data-testid="timelapse-download">{state.name}</a> ({(state.bytes / 1024).toFixed(0)} KiB). One second per observation.</p>}
    {state.status === 'error' && <p className="error" role="alert">{state.message}</p>}
    <p className="result-note">The video carries its own caveats on every frame: {CAVEATS.join(' ')}</p>
  </div>;
}


function EpochComparison({frames, index, target}) {
  const previous=previousEpoch(frames,index), current=frames[index];
  const [opened,setOpened]=useState(null), [cache,setCache]=useState({});
  const key=previous ? `${target.ra}|${target.dec}|${previous.access_url}|${current.access_url}` : null;
  const targetKey=`${target.ra}|${target.dec}`;
  return <div aria-label="Epoch change analysis" role="region">
    <h3>Compare real epochs</h3>
    <p>{previous ? `Earlier same-detector observation: ${previous.obs_id}. This is a preliminary shortlist; the comparison checks scientific compatibility.` : 'No earlier observation with the same detector, collection and at least one hour separation is available in this sequence.'}</p>
    {previous && <button onClick={()=>setOpened(key)} disabled={opened===key}>Compare with previous observation</button>}
    {cache[key] && <p>{cache[key].detection?.conclusion}</p>}
    {Object.entries(cache).filter(([id])=>id.startsWith(targetKey+'|')).map(([id,data])=><button key={id} onClick={()=>setOpened(id)}>Assessed pair: {data.frames.map(f=>f.obs_id).join(' → ')}</button>)}
    {opened!==key && cache[opened] && opened.startsWith(targetKey+'|') && <div><h4>Previously assessed pair</h4><ComparisonResult key={opened} result={cache[opened]}/></div>}
    {previous && opened===key && <ComparePanel key={key} picks={{a:previous,b:current}} target={target}
      onRemove={()=>setOpened(null)} onSwap={()=>setOpened(null)} initialResult={cache[key]}
      onResult={data=>setCache(old=>Object.fromEntries([...Object.entries(old).filter(([id])=>id!==key),[key,data]].slice(-6)))}/>}
  </div>;
}

export default function TemporalImageExplorer({result, loading, error, target}) {
  const sequence = useMemo(() => chronologicalFrames(loading ? [] : result?.observations), [loading, result]);
  const signature = sequence.frames.map(frame => `${frame.obs_id}|${frame.observed_at_utc}|${frame.energy_bandpassname}|${frame.access_url}`).join('\n');
  const [index, setIndex] = useState(0);
  const [seen, setSeen] = useState(signature);
  const [metadata, setMetadata] = useState(null);
  const [imageError, setImageError] = useState('');
  const [imageLoading, setImageLoading] = useState(false);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const [playing, setPlaying] = useState(false);
  // Key of the frame whose image finished loading (or failing). Tied to the frame, so a previous
  // frame's state can never count as the current one being ready.
  const [settledKey, setSettledKey] = useState(null);
  const displayIndex = !sequence.frames.length || seen !== signature ? 0 : Math.min(index, sequence.frames.length - 1);
  if (seen !== signature) {setSeen(signature); setIndex(0); setPlaying(false);}

  const frame = sequence.frames[displayIndex] || null;
  const moving=frame?.demo_target_id==='3i-atlas';
  const [trackingView,setTrackingView]=useState('fixed_sky');
  const elapsed = useElapsed(imageLoading && frame ? `${frame.access_url}|${target.ra}|${target.dec}|${retry}` : null);
  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    setMetadata(null); setImageError(''); setPreviewFailed(false);
    if (!frame) {setImageLoading(false); return () => controller.abort();}
    setImageLoading(true);
    const loadKey = `${frame.access_url}|${retry}|${moving?trackingView:'native'}`;
    loadObservationImage(frame, target, {signal: controller.signal,trackingView:moving?trackingView:undefined})
      .then(data => {if (!cancelled) setMetadata(data);})
      .catch(err => {if (!cancelled && err?.name !== 'AbortError') {setImageError(err.message || 'This observation image could not be loaded.'); setSettledKey(loadKey);}})
      .finally(() => {if (!cancelled) setImageLoading(false);});
    return () => {cancelled = true; controller.abort();};
  }, [frame, target, retry, moving, trackingView]);

  const last = sequence.frames.length - 1;
  const frameKey = frame ? `${frame.access_url}|${retry}|${moving?trackingView:'native'}` : null;
  const settled = Boolean(frameKey) && settledKey === frameKey;
  useEffect(() => {
    // Advance only after the current frame has loaded (or failed), then show it for PLAY_DWELL_MS.
    if (!playing || !frame || !settled) return undefined;
    if (displayIndex >= last) {setPlaying(false); return undefined;}
    const timer = setTimeout(() => setIndex(displayIndex + 1), PLAY_DWELL_MS);
    return () => clearTimeout(timer);
  }, [playing, settled, displayIndex, last, frame]);
  function togglePlay() {
    if (playing) {setPlaying(false); return;}
    if (displayIndex >= last) setIndex(0);  // Replay from the first observation.
    setPlaying(true);
  }

  const bandpasses = [...new Set(sequence.frames.map(item => item.energy_bandpassname).filter(Boolean))];
  const timeLabel = frame ? formatUtcLabel(frame.observed_at_utc) : '';

  return <section className="panel time-explorer" aria-label="Astronomical time explorer" aria-busy={loading || imageLoading}>
    <div className="section-heading"><div><div className="eyebrow">OBSERVATION TIME</div><h2>Time slider</h2></div><span className={`tag ${frame && metadata ? 'live' : ''}`}>{loading ? 'Waiting for search' : imageError || previewFailed ? 'Image unavailable' : frame ? result?.mode === 'demo' ? 'Preloaded sequence' : 'Archive sequence' : 'No sequence'}</span></div>
    {loading ? <p className="empty" role="status">Waiting for the observation search to finish. The time slider resets for each target.</p>
      : error ? <p className="error" role="alert">No time sequence is available. {error}</p>
      : !result ? <p className="empty">Search SPHEREx observations for the selected point to build a time sequence.</p>
      : !sequence.frames.length ? <p className="empty">{result.count ? 'None of the returned observations include a usable image link.' : 'No observations were returned for this point, so there is no time sequence.'}</p>
      : <>
        {result?.mode === 'demo' && <p className="demo-notice" role="note">{moving ? 'Preserved native assets keep their original orientation. Tracking previews below use celestial WCS reprojection; stationary-source alignment has not been independently certified. No source motion or brightness variation has been validated.' : result.science_note}</p>}
        <div className="time-readout" aria-live="polite">
          <p className="time-current" data-testid="time-slider-time">{timeLabel}</p>
          <p data-testid="time-slider-id">Observation {frame.obs_id || '—'}</p>
          <p className="result-note">Step {displayIndex + 1} of {sequence.frames.length}. Each step is one observation, not an equal interval of time.</p>
        </div>
        {isSyntheticObservation(frame, metadata) && <p className="synthetic-banner" role="note">Synthetic fixture. This image is not a live NASA observation.</p>}
        <div className="image-facts">
          <div><span>Archive time (UTC)</span><strong>{timeLabel}</strong></div>
          <div><span>Observation ID</span><strong>{frame.obs_id || '—'}</strong></div>
          <div><span>Bandpass / detector</span><strong>{frame.energy_bandpassname || '—'}{metadata?.detector != null ? ` · detector ${metadata.detector}` : ''}</strong></div>
          <div><span>Archive wavelength bounds</span><strong>{wavelengthLabel(frame)}</strong></div>
          <div><span>Collection</span><strong>{frame.obs_collection || '—'}</strong></div>
          <div><span>{moving ? 'Wavelength at predicted comet (approximate)' : 'Center wavelength'}</span><strong>{moving && metadata?.tracking ? `${Number(metadata.tracking.frames[0].target_wavelength_um).toFixed(3)} µm` : metadata?.center?.spectral ? `${Number(metadata.center.spectral.wavelength_um).toFixed(3)} µm` : imageLoading ? 'Loading…' : '—'}</strong></div>
        </div>
        {metadata?.observed_at_utc && parseUtc(metadata.observed_at_utc) !== parseUtc(frame.observed_at_utc) && <p className="result-note">FITS header time differs from the archive timestamp: {formatUtcLabel(metadata.observed_at_utc)}.</p>}
        {metadata?.acquisition && <p className="result-note">{metadata.acquisition.data_release} · calibration {metadata.acquisition.calibration} · {metadata.acquisition.position_mode}. {metadata.acquisition.predicted_ra != null
          ? `Frame centre ICRS ${metadata.acquisition.ra.toFixed(6)}°, ${metadata.acquisition.dec.toFixed(6)}°; marker at the predicted position for this exposure, ICRS ${metadata.acquisition.predicted_ra.toFixed(6)}°, ${metadata.acquisition.predicted_dec.toFixed(6)}°.`
          : `Predicted/reference ICRS ${metadata.acquisition.ra.toFixed(6)}°, ${metadata.acquisition.dec.toFixed(6)}°.`} No measured source position is inferred from the marker.</p>}
        {moving && <div><label>Comet playback view <select aria-label="Comet playback view" value={trackingView} onChange={e=>{setPlaying(false);setTrackingView(e.target.value);}}><option value="fixed_sky">Fixed sky — background stars stay aligned</option><option value="comet_centered">Follow predicted comet — background stars move</option></select></label>
          <p>Dashed ring: official predicted position, not a measured comet detection. Each frame keeps its own display stretch; brightness is not comparable by eye.</p>
          {metadata?.tracking && <p role="note">{metadata.tracking.conclusion} Image check: {metadata.tracking.frames[0].image_measurement.status==='unconfirmed_local_excess' ? 'a local excess is present near the prediction, but source identity is unverified.' : 'no reliable local excess was established.'}</p>}
        </div>}
        <div className="time-stage" style={moving?{position:'relative'}:undefined}>
          {imageLoading && <DownloadProgress title={`Loading the observation preview for ${frame.obs_id || 'this step'}`} local={Boolean(frame.demo)} elapsed={elapsed}/>}
          {imageError && <p className="image-loading error" role="alert">{imageError}</p>}
          {metadata?.preview_url && !previewFailed && !moving && <img data-testid="time-slider-image" src={metadata.preview_url} alt={`${frame.obs_id || 'SPHEREx observation'} at ${timeLabel}`} onLoad={() => setSettledKey(frameKey)} onError={() => {setPreviewFailed(true); setSettledKey(frameKey);}}/>}
          {moving && metadata?.tracking && metadata?.preview_url && !previewFailed && <svg data-testid="time-slider-image" viewBox={`0 0 ${metadata.tracking_grid.shape[1]} ${metadata.tracking_grid.shape[0]}`} style={{width:'100%',maxHeight:500}} role="img" aria-label={`Real comet observation ${frame.obs_id}, predicted position marked`}>
            <image href={metadata.preview_url} width={metadata.tracking_grid.shape[1]} height={metadata.tracking_grid.shape[0]} onLoad={()=>setSettledKey(frameKey)} onError={()=>{setPreviewFailed(true);setSettledKey(frameKey);}}/>
            <circle data-testid="predicted-comet-marker" cx={metadata.tracking.frames[0].marker.x+.5} cy={metadata.tracking_grid.shape[0]-.5-metadata.tracking.frames[0].marker.y} r="4" fill="none" stroke="cyan" strokeDasharray="2 1"/>
          </svg>}
          {previewFailed && <p className="image-loading error" role="alert">The preview image failed to load. Choose another observation or retry this one.</p>}
        </div>
        {(imageError || previewFailed) && !imageLoading && <button type="button" className="secondary reload-image" onClick={() => setRetry(count => count + 1)}>Retry this observation image</button>}
        <TimeSlider count={sequence.frames.length} index={displayIndex} onChange={setIndex} label={`${timeLabel}, ${frame.obs_id || 'observation'}`}
          playing={playing} onTogglePlay={sequence.frames.length > 1 ? togglePlay : null} atEnd={displayIndex >= last}/>
        {playing && <p className="result-note" role="status" data-testid="playback-status">{settled ? `Playing: step ${displayIndex + 1} of ${sequence.frames.length}.` : `Playing: waiting for step ${displayIndex + 1} to load before moving on.`}</p>}
        <div className="time-ends"><span>{formatUtcLabel(sequence.frames[0].observed_at_utc)}</span><span>{formatUtcLabel(sequence.frames[sequence.frames.length - 1].observed_at_utc)}</span></div>
        <p className="result-note">Slider positions are ordered by archive time. A large gap between observations is still a single step.</p>
        <EpochComparison frames={sequence.frames} index={displayIndex} target={target}/>
        {!moving && <TimelapseExport key={`${target.ra}|${target.dec}|${signature}`} frames={sequence.frames} target={target} mode={result?.mode}/>}
        {moving && <p>Video export is unavailable for tracking views; playback remains available. No measured brightness or coma change is inferred.</p>}
        <p className="image-science-note">{moving ? 'Tracking views use the real FITS data and predicted per-exposure positions. WCS reprojection is not independent astrometric validation. No physical change is established.' : 'These are raw observation images. They are not spatially registered, and this slider does not detect moving objects or subtract frames.'}</p>
        {bandpasses.length > 1 && <p className="image-science-note">This sequence mixes bandpasses ({bandpasses.join(', ')}). Those images are not spectrally equivalent.</p>}
        {sequence.skippedCount > 0 && <p className="result-note">{sequence.skippedCount} observation{sequence.skippedCount === 1 ? '' : 's'} had no usable image link and {sequence.skippedCount === 1 ? 'is' : 'are'} not on the slider.</p>}
        {sequence.undatedCount > 0 && <p className="result-note">{sequence.undatedCount} observation{sequence.undatedCount === 1 ? '' : 's'} had no archive timestamp and {sequence.undatedCount === 1 ? 'is' : 'are'} placed after the dated frames.</p>}
        {metadata?.wavelength_note && <p className="result-note">{metadata.wavelength_note}</p>}
      </>}
  </section>;
}
