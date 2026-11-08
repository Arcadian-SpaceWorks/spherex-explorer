import { useEffect, useRef, useState } from 'react';
import { MODES, detectorOf, formatSeparation, hoursApart, pairHints, requestComparison, suggestMode } from '../compareAdapter';
import { formatUtcLabel, wavelengthLabel, parseUtc } from '../timeline';
import DownloadProgress, { useElapsed } from './DownloadProgress';

const number = (value, digits) => value == null ? '—' : Number(value).toFixed(digits);
const reducedMotion = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

function Slot({role, row, onRemove}) {
  return <div className={`compare-slot ${row ? 'filled' : ''}`} data-testid={`compare-slot-${role}`}>
    <span className="compare-role" aria-hidden="true">{role.toUpperCase()}</span>
    {row ? <div>
      <strong>{formatUtcLabel(row.observed_at_utc)}</strong>
      <span>{row.energy_bandpassname || 'Infrared band unavailable'}</span>
      <small>Observation {row.obs_id || '—'}</small>
      <small>Archive range {wavelengthLabel(row)}</small>
    </div> : <div><strong>Not chosen</strong><span>Press “{role.toUpperCase()}” on a row in the table above.</span></div>}
    {row && <button type="button" className="compare-remove" onClick={() => onRemove(role)} aria-label={`Remove ${role.toUpperCase()}`}>×</button>}
  </div>;
}

function Frame({frame, src, label}) {
  return <figure className="compare-frame">
    <img src={src} alt={`${label}: ${frame.obs_id}, ${frame.band}, ${formatUtcLabel(frame.observed_at_utc)}, north up`} data-testid={`compare-image-${frame.role}`}/>
    <figcaption><b>{label}</b> {formatUtcLabel(frame.observed_at_utc).replace(' UTC', '')} · {frame.band} · {number(frame.wavelength_um, 3)} µm</figcaption>
  </figure>;
}

function Blink({result}) {
  const [shown, setShown] = useState('a');
  const [playing, setPlaying] = useState(() => !reducedMotion());
  const playingRef = useRef(playing);
  playingRef.current = playing;
  useEffect(() => {
    // One tick at a time; a tick that fires after a pause or a manual step is ignored.
    if (!playing) return undefined;
    const timer = setTimeout(() => {if (playingRef.current) setShown(role => role === 'a' ? 'b' : 'a');}, 1000);
    return () => clearTimeout(timer);
  }, [playing, shown]);
  function show(role) {playingRef.current = false; setPlaying(false); setShown(role);}
  const frame = result.frames.find(item => item.role === shown);
  return <div className="compare-blink">
    <div className="compare-blink-stage" data-testid="compare-blink" data-shown={shown}>
      {result.frames.map(item => <img key={item.role} src={result.previews[item.role]} hidden={item.role !== shown}
        alt={`${item.role.toUpperCase()}: ${item.obs_id}, ${formatUtcLabel(item.observed_at_utc)}, north up`}/>)}
      <span className="compare-blink-label" aria-live="polite">{shown.toUpperCase()} · {formatUtcLabel(frame.observed_at_utc).replace(' UTC', '')} · {frame.band} · {number(frame.wavelength_um, 3)} µm</span>
    </div>
    <div className="compare-blink-controls">
      <button type="button" className="secondary" onClick={() => setPlaying(value => !value)} aria-pressed={playing}>{playing ? 'Pause blink' : 'Play blink'}</button>
      <button type="button" className="secondary" onClick={() => show('a')} aria-pressed={shown === 'a'}>Show A</button>
      <button type="button" className="secondary" onClick={() => show('b')} aria-pressed={shown === 'b'}>Show B</button>
    </div>
  </div>;
}

export function ComparisonResult({result}) {
  const [view, setView] = useState('side');
  const [selectedCandidate,setSelectedCandidate]=useState(null);
  const candidates=result.context === 'real_observation_comparison' && result.detection?.status === 'screened' && result.validation.difference_allowed ? result.detection.candidates : [];
  const mode = result.validation.mode;
  const differenceReason = mode === 'wavelength'
    ? 'Images at different wavelengths are never subtracted.'
    : result.validation.reasons.filter(reason => reason.severity !== 'info').map(reason => reason.detail).join(' ') || 'Not allowed for this pair.';
  const frames = result.frames;
  const firstTime=parseUtc(frames[0].observed_at_utc), secondTime=parseUtc(frames[1].observed_at_utc);
  const dated=firstTime!=null && secondTime!=null && firstTime!==secondTime;
  const aEarlier=dated && firstTime<secondTime;
  const chronological=mode==='time' && dated ? [...frames].sort((a,b)=>parseUtc(a.observed_at_utc)-parseUtc(b.observed_at_utc)) : frames;
  const labelFor=f=>mode==='time' && dated ? ((f.role==='a')===aEarlier ? 'Before' : 'After') : `View ${f.role.toUpperCase()}`;
  const outcome=(result.detection?.status === 'screened' && result.context === 'real_observation_comparison' && result.validation.difference_allowed ? (candidates.length ? 'POSSIBLE CHANGE FOUND' : 'NO SUPPORTED CHANGE') : result.detection?.outcome) || (result.previews.difference ? 'VISUAL DIFFERENCES ONLY' : 'IMAGES CANNOT BE RELIABLY COMPARED');
  return <div className="compare-result" data-testid="compare-result">
    <div className={`compare-verdict verdict-${result.decision.toLowerCase()}`} data-testid="compare-verdict">
      <strong>{outcome}</strong>
    </div>
    <p className="compare-explanation">{result.detection?.conclusion || 'These images can be viewed together, but their differences do not establish an astronomical change.'}</p>
    <p>{formatSeparation(result.validation.time_separation_hours)} between observations. {result.stretch.shared ? 'Before and After use the same display brightness scale.' : 'Each image uses its own display scale; brightness cannot be compared by eye.'}</p>
    <div className="compare-tabs" role="group" aria-label="Comparison view">
      <button type="button" aria-pressed={view === 'side'} onClick={() => setView('side')}>Side by side</button>
      <button type="button" aria-pressed={view === 'blink'} onClick={() => setView('blink')}>Blink</button>
      <button type="button" aria-pressed={view === 'difference'} disabled={!result.previews.difference}
        title={result.previews.difference ? undefined : differenceReason} onClick={() => setView('difference')}>Difference</button>
    </div>
    {!result.previews.difference && <p className="result-note" data-testid="difference-unavailable">Differences are unavailable for this pair. You can still view the two original images.</p>}
    {view === 'side' && <div className="compare-side">
      {chronological.map(frame => <Frame key={frame.role} frame={frame} src={result.previews[frame.role]} label={labelFor(frame)}/>)}
    </div>}
    {view === 'blink' && <Blink result={result}/>}
    {(view === 'difference' || view === 'side') && result.previews.difference && <figure className="compare-frame compare-difference">
      <div style={{position:'relative'}}>
      <img style={{display:'block',width:'100%'}} src={result.previews.difference} alt="Difference B minus A, north up" data-testid="compare-image-difference"/>
      {candidates.length>0 && <svg viewBox={`0 0 ${result.grid.shape[1]} ${result.grid.shape[0]}`} style={{position:'absolute',inset:0,width:'100%',height:'100%'}} aria-label="Real observation candidate positions">
        {candidates.map(c=><circle key={c.id} cx={c.x+.5} cy={result.grid.shape[0]-.5-c.y} r="4" fill="none" stroke="cyan" role="button" tabIndex={0} aria-label={`Select candidate ${c.id}`} onKeyDown={e=>{if(e.key==='Enter' || e.key===' '){e.preventDefault();setSelectedCandidate(c);}}} onClick={()=>setSelectedCandidate(c)}/>)}
      </svg>}</div>
      <figcaption><b>Differences — {aEarlier ? 'After minus Before' : 'B minus A'} (B − A)</b> {result.difference.display.meaning} Measured residual spread {number(result.difference.robust_noise, 3)} MJy/sr (not calibrated uncertainty).
        Violet pixels are masked in A or B, not changes. This is not a validated change: residuals at bright sources can come from resampling and image sharpness.</figcaption>
    </figure>}
    <p className="result-note" data-testid="compare-legend"><span className="mask-key" aria-hidden="true"/>Violet marks masked pixels (no valid data in that image). North is up, east is left.</p>
    {selectedCandidate && <p role="status">{selectedCandidate.id}: ICRS {number(selectedCandidate.ra,6)}, {number(selectedCandidate.dec,6)}. {selectedCandidate.interpretation}; peak residual {number(selectedCandidate.peak_residual,4)} MJy/sr. Calibrated uncertainty unavailable unless explicitly supplied.</p>}
    <details className="comparison-details"><summary>How did we reach this conclusion?</summary>
    <ul className="compare-reasons">{result.validation.reasons.map(reason => <li key={reason.code}>{reason.detail}</li>)}</ul>
    <div className="table-scroll"><table className="compare-facts"><thead><tr><th></th><th>A</th><th>B</th></tr></thead><tbody>
      <tr><th>Observation</th>{frames.map(f => <td key={f.role}>{f.obs_id}</td>)}</tr>
      <tr><th>Observed (UTC)</th>{frames.map(f => <td key={f.role}>{formatUtcLabel(f.observed_at_utc)}</td>)}</tr>
      <tr><th>Detector</th>{frames.map(f => <td key={f.role}>{f.band}</td>)}</tr>
      <tr><th>Wavelength at target (approx.)</th>{frames.map(f => <td key={f.role}>{number(f.wavelength_um, 4)} µm</td>)}</tr>
      <tr><th>Core level, raw (MJy/sr)</th>{frames.map(f => <td key={f.role}>{number(f.diagnostics?.core_median, 3)}</td>)}</tr>
      <tr><th>Source</th>{frames.map(f => <td key={f.role}>{f.provenance?.source === 'irsa_cutout' ? 'IRSA cutout' : f.provenance?.source || '—'}</td>)}</tr>
    </tbody></table></div>
    <p className="result-note" data-testid="compare-summary">Overlap {Math.round(result.overlap_fraction * 100)}% · wavelength difference {number(result.validation.wavelength_delta_um, 4)} µm · {formatSeparation(result.validation.time_separation_hours)} apart{result.cache_hit ? ' · from the comparison cache' : ''}</p>
    {result.detection && <section aria-label="Scientific change detection">
      <h3>Scientific change detection</h3>
      <p>{result.detection.status === 'unavailable' ? 'Visual comparison only — scientific change detection unavailable.' : result.detection.status}</p>
      <p>{result.detection.conclusion}</p>
      {candidates.length>0 && <div className="table-scroll"><table><thead><tr><th>Candidate</th><th>ICRS RA / Dec</th><th>Peak residual</th><th>Uncertainty</th></tr></thead><tbody>
        {candidates.map(c=><tr key={c.id}><td><button onClick={()=>setSelectedCandidate(c)}>{c.id}</button></td><td>{number(c.ra,6)} / {number(c.dec,6)}</td><td>{number(c.peak_residual,4)} MJy/sr</td><td>{c.uncertainty ?? 'Not calibrated'}</td></tr>)}
      </tbody></table></div>}

      <div>
        <p>{result.detection.follow_up}</p>
        <ul>{result.detection.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
        <ul>{result.detection.limitations.map(reason => <li key={reason}>{reason}</li>)}</ul>
        {result.detection.checks?.map(check => <p key={check.code}>{check.explanation}</p>)}
        <p>Actual observation dates and wavelengths are listed above. A visual difference is not a calibrated measurement of source variability.</p>
        {result.detection.registration_diagnostics && <p>Image-feature alignment: {result.detection.registration_diagnostics.matches} matched peaks. RMS separation {number(result.detection.registration_diagnostics.rms_separation_pixels,3)} pixels. These peaks have not been identified as stationary sources.</p>}
        {result.detection.variance_propagation && <p>Noise propagation: {result.detection.variance_propagation.method}. Median difference variance {number(result.detection.variance_propagation.median_difference_variance,6)} (MJy/sr)². {result.detection.variance_propagation.limitation}</p>}
        {frames.map(f=><div key={f.role}><h4>{f.role === 'a' ? 'Before' : 'After'}: calibration evidence</h4>
          <p>Pipeline version: {f.diagnostics?.pipeline_version || 'Unavailable'}. PSF (image sharpness model): {f.diagnostics?.local_psf?.status || 'Unavailable'}; local model RMS width {number(f.diagnostics?.local_psf?.rms_width_native_pixels,3)} native pixels. No field-wide matching is certified.</p>
          <p>Original file SHA-256: {f.sha256 || f.provenance?.sha256 || 'Unavailable'}</p>
          {f.fits_url && <a href={f.fits_url} target="_blank" rel="noreferrer">Archive source for {f.role.toUpperCase()}</a>}
        </div>)}
      </div>
    </section>}
    {result.notes.map(note => <p key={note} className="image-science-note">{note}</p>)}
    </details>
  </div>;
}

export default function ComparePanel({picks, target, onRemove, onSwap, initialResult = null, onResult}) {
  const {a, b} = picks;
  const [mode, setMode] = useState(() => suggestMode(a, b));
  const [result, setResult] = useState(initialResult), [error, setError] = useState('');
  const [loading, setLoading] = useState(false), [run, setRun] = useState(0);
  const request = useRef(null);
  const elapsed = useElapsed(loading ? run : null);
  useEffect(() => () => request.current?.abort(), []);
  const ready = Boolean(a && b);
  const suggested = suggestMode(a, b);
  const hints = pairHints(a, b, mode);

  async function compare() {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setRun(n => n + 1); setLoading(true); setResult(null); setError('');
    try {
      const data = await requestComparison({a, b, target, mode, signal: controller.signal});
      if (request.current === controller) {setResult(data); onResult?.(data);}
    } catch (err) {
      if (request.current === controller && controller.signal.reason !== 'user') setError(err.message);
    } finally {
      if (request.current === controller) setLoading(false);
    }
  }
  function chooseMode(next) {request.current?.abort(); request.current=null; setLoading(false); setMode(next); setResult(null); setError('');}

  return <section className="panel compare-panel" aria-label="Image comparison" aria-busy={loading}>
    <div className="section-heading"><div><div className="eyebrow">COMPARE</div><h2>Compare two views of the same region of space</h2></div>
      <span className={`tag ${result ? 'live' : ''}`}>{loading ? 'Comparing' : result ? (a?.demo ? 'Preloaded real observations' : 'Live IRSA data') : ready ? 'Ready to compare' : 'Choose A and B'}</span></div>
    <div className="compare-tray">
      <Slot role="a" row={a} onRemove={onRemove}/>
      <button type="button" className="secondary compare-swap" onClick={onSwap} disabled={!a && !b} aria-label="Swap A and B">⇄</button>
      <Slot role="b" row={b} onRemove={onRemove}/>
    </div>
    <p className="result-note">1. Choose A and B in the observations table. 2. Find Changes. 3. Read what the images can tell us.</p>
    <div className="compare-mode" role="group" aria-label="Comparison mode">
      {Object.entries(MODES).map(([id, item]) => <button key={id} type="button" aria-pressed={mode === id} onClick={() => chooseMode(id)}>
        {item.label}{ready && id === suggested ? ' (suggested)' : ''}</button>)}
    </div>
    <p className="result-note">{MODES[mode].description}</p>
    {hints.map(hint => <p key={hint} className="compare-hint" role="note">{hint}</p>)}
    {ready && a && b && <p className="result-note">{detectorOf(a) === detectorOf(b) ? 'Same detector' : 'Different detectors'} · {formatSeparation(hoursApart(a, b))} apart (archive times).</p>}
    <button type="button" className="compare-run" disabled={!ready || loading || hints.some(hint => hint.startsWith('A and B are the same'))} onClick={compare}>
      {loading ? 'Analyzing observations…' : 'Find Changes'}</button>
    {loading && <DownloadProgress title="Preparing the real images and checking whether their differences can be interpreted" local={Boolean(a?.demo && b?.demo)} elapsed={elapsed}
      onCancel={() => {request.current?.abort('user'); setLoading(false);}}/>}
    {error && <p className="error" role="alert">{error}</p>}
    {result && <ComparisonResult key={result.compare_id} result={result}/>}
  </section>;
}
