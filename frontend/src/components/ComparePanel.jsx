import { useEffect, useRef, useState } from 'react';
import { MODES, detectorOf, formatSeparation, hoursApart, pairHints, requestComparison, suggestMode } from '../compareAdapter';
import { formatUtcLabel, wavelengthLabel } from '../timeline';
import DownloadProgress, { useElapsed } from './DownloadProgress';

const VERDICTS = {
  ACCEPT: {time: 'Visual difference available', wavelength: 'Side by side'},
  WARN: {time: 'Blink only', wavelength: 'Side by side, with caveats'},
  REJECT: {time: 'Not directly comparable', wavelength: 'Not comparable'},
};
const number = (value, digits) => value == null ? '—' : Number(value).toFixed(digits);
const reducedMotion = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

function Slot({role, row, onRemove}) {
  return <div className={`compare-slot ${row ? 'filled' : ''}`} data-testid={`compare-slot-${role}`}>
    <span className="compare-role" aria-hidden="true">{role.toUpperCase()}</span>
    {row ? <div>
      <strong>{row.obs_id || 'Observation'}</strong>
      <span>{formatUtcLabel(row.observed_at_utc)} · {row.energy_bandpassname || '—'}</span>
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

function Result({result}) {
  const [view, setView] = useState('side');
  const mode = result.validation.mode;
  const differenceReason = mode === 'wavelength'
    ? 'Images at different wavelengths are never subtracted.'
    : result.validation.reasons.filter(reason => reason.severity !== 'info').map(reason => reason.detail).join(' ') || 'Not allowed for this pair.';
  const frames = result.frames;
  return <div className="compare-result" data-testid="compare-result">
    <div className={`compare-verdict verdict-${result.decision.toLowerCase()}`} data-testid="compare-verdict">
      <strong>{result.decision}</strong><span>{VERDICTS[result.decision][mode]}</span>
    </div>
    <ul className="compare-reasons">
      {result.validation.reasons.map(reason => <li key={reason.code} className={`reason-${reason.severity}`}>{reason.detail}</li>)}
    </ul>
    <div className="compare-tabs" role="group" aria-label="Comparison view">
      <button type="button" aria-pressed={view === 'side'} onClick={() => setView('side')}>Side by side</button>
      <button type="button" aria-pressed={view === 'blink'} onClick={() => setView('blink')}>Blink</button>
      <button type="button" aria-pressed={view === 'difference'} disabled={!result.previews.difference}
        title={result.previews.difference ? undefined : differenceReason} onClick={() => setView('difference')}>Difference</button>
    </div>
    {!result.previews.difference && <p className="result-note" data-testid="difference-unavailable">No difference image: {differenceReason}</p>}
    {view === 'side' && <div className="compare-side">
      {frames.map(frame => <Frame key={frame.role} frame={frame} src={result.previews[frame.role]} label={frame.role.toUpperCase()}/>)}
    </div>}
    {view === 'blink' && <Blink result={result}/>}
    {view === 'difference' && result.previews.difference && <figure className="compare-frame compare-difference">
      <img src={result.previews.difference} alt="Difference B minus A, north up" data-testid="compare-image-difference"/>
      <figcaption><b>B − A</b> {result.difference.display.meaning} Typical noise {number(result.difference.robust_noise, 3)} MJy/sr.
        Violet pixels are masked in A or B, not changes. This is not a validated change: residuals at bright sources can come from resampling and image sharpness.</figcaption>
    </figure>}
    <p className="result-note" data-testid="compare-legend"><span className="mask-key" aria-hidden="true"/>Violet marks masked pixels (no valid data in that image). North is up, east is left.</p>
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
      <ul>{result.detection.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
      <ul>{result.detection.limitations.map(reason => <li key={reason}>{reason}</li>)}</ul>
    </section>}
    {result.notes.map(note => <p key={note} className="image-science-note">{note}</p>)}
  </div>;
}

export default function ComparePanel({picks, target, onRemove, onSwap}) {
  const {a, b} = picks;
  const [mode, setMode] = useState(() => suggestMode(a, b));
  const [result, setResult] = useState(null), [error, setError] = useState('');
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
      if (request.current === controller) setResult(data);
    } catch (err) {
      if (request.current === controller && controller.signal.reason !== 'user') setError(err.message);
    } finally {
      if (request.current === controller) setLoading(false);
    }
  }
  function chooseMode(next) {setMode(next); setResult(null); setError('');}

  return <section className="panel compare-panel" aria-label="Image comparison" aria-busy={loading}>
    <div className="section-heading"><div><div className="eyebrow">COMPARE</div><h2>Compare two observations</h2></div>
      <span className={`tag ${result ? 'live' : ''}`}>{loading ? 'Comparing' : result ? 'Live IRSA data' : ready ? 'Ready to compare' : 'Choose A and B'}</span></div>
    <div className="compare-tray">
      <Slot role="a" row={a} onRemove={onRemove}/>
      <button type="button" className="secondary compare-swap" onClick={onSwap} disabled={!a && !b} aria-label="Swap A and B">⇄</button>
      <Slot role="b" row={b} onRemove={onRemove}/>
    </div>
    <p className="result-note">The table shows at most 100 observations. Filter by detector to see every observation of one band.</p>
    <div className="compare-mode" role="group" aria-label="Comparison mode">
      {Object.entries(MODES).map(([id, item]) => <button key={id} type="button" aria-pressed={mode === id} onClick={() => chooseMode(id)}>
        {item.label}{ready && id === suggested ? ' (suggested)' : ''}</button>)}
    </div>
    <p className="result-note">{MODES[mode].description}</p>
    {hints.map(hint => <p key={hint} className="compare-hint" role="note">{hint}</p>)}
    {ready && a && b && <p className="result-note">{detectorOf(a) === detectorOf(b) ? 'Same detector' : 'Different detectors'} · {formatSeparation(hoursApart(a, b))} apart (archive times).</p>}
    <button type="button" className="compare-run" disabled={!ready || loading || hints.some(hint => hint.startsWith('A and B are the same'))} onClick={compare}>
      {result || error ? 'Compare again' : 'Compare A and B'}</button>
    <button type="button" className="secondary" disabled={!ready || loading || mode !== 'time'} onClick={compare}>Detect Changes — check scientific eligibility</button>
    {loading && <DownloadProgress title="Downloading both cutouts from IRSA and aligning them" elapsed={elapsed}
      onCancel={() => {request.current?.abort('user'); setLoading(false);}}/>}
    {error && <p className="error" role="alert">{error}</p>}
    {result && <Result key={result.compare_id} result={result}/>}
  </section>;
}
