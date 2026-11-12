import { useEffect, useMemo, useRef, useState } from 'react';
import SpectrumChart from './SpectrumChart';
import { GUIDED_TARGETS } from '../spectrumTargets';
import { describeFeature, fetchDemoSpectrum, fetchFeatures, fetchReference, fetchSpectrum, formatFlux, outcomeSummary,
  redshiftedLines, seasonLabel, seasonSeries, shortDate, startSpectrum, usablePoints, wideRange } from '../spectrum';

const POLL_MS = 1500;

function csvOf(job) {
  const keys = ['wavelength_um', 'bandwidth_um', 'flux_mjy', 'flux_err_mjy', 'status', 'utc', 'mjd', 'detector', 'obs_id', 'collection', 'ra', 'dec', 'flag_names', 'background_mjy_sr'];
  const head = ['# SPHEREx forced-photometry spectrum. Flux densities in mJy, wavelengths in micrometres.', `# Request: ${JSON.stringify(job.request)}`,
    ...['source', 'photometry', 'background', 'uncertainty', 'wavelength', 'rejected'].map(key => `# ${key}: ${job.method[key]}`),
    ...job.method.limits.map(line => `# limit: ${line}`)];
  const rows = [...job.points].sort((a, b) => (a.wavelength_um ?? 99) - (b.wavelength_um ?? 99))
    .map(point => keys.map(key => Array.isArray(point[key]) ? point[key].join(' ') : point[key] ?? '').join(','));
  return [...head, keys.join(','), ...rows].join('\n') + '\n';
}

function Findings({results, features, thresholds}) {
  const byId = new Map(features.map(feature => [feature.id, feature]));
  const detected = results.filter(result => result.status === 'detected' && byId.has(result.id));
  const absent = results.filter(result => result.status === 'not_detected' && byId.has(result.id));
  const unmeasured = results.filter(result => result.status === 'not_measurable' && byId.has(result.id));
  return <>
    {detected.length > 0 ? <ul className="spectrum-findings">{detected.map(result => {
      const feature = byId.get(result.id);
      return <li key={result.id} data-testid={`finding-${result.id}`}>
        <div><strong>{feature.label}</strong><span className="tag">{result.kind}</span><small>{Math.abs(result.significance) > 100 ? 'over 100' : Math.abs(result.significance).toFixed(0)}σ · {result.points.core} exposures in band</small></div>
        <p>{describeFeature(result, feature)} {feature.meaning}</p>
        {feature.caveat && !(result.kind === 'emission' && feature.kinds.length > 1) && <p className="spectrum-caveat">Check: {feature.caveat}</p>}
      </li>;
    })}</ul> : <p className="spectrum-none">No band passes the detection threshold ({thresholds?.sigma ?? 5}σ and at least {Math.round((thresholds?.strength ?? 0.08) * 100)}% of the continuum).</p>}
    {absent.length > 0 && <p className="spectrum-absent">Looked for and not found: {absent.map(result => byId.get(result.id).label).join(', ')}.</p>}
    {unmeasured.length > 0 && <p className="spectrum-absent">Not enough exposures to test: {unmeasured.map(result => byId.get(result.id).label).join(', ')}.</p>}
  </>;
}

export default function SpectrumPanel({mode, selected, demoTargetId, onGo}) {
  const [job, setJob] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [catalogue, setCatalogue] = useState(null), [reference, setReference] = useState(null);
  const [logChoice, setLog] = useState(null), [redshift, setRedshift] = useState(''), [label, setLabel] = useState('');
  const run = useRef(null);
  const stop = () => {run.current?.abort(); run.current = null;};
  useEffect(() => {
    const controller = new AbortController();
    fetchFeatures({signal: controller.signal}).then(setCatalogue).catch(() => {});
    return () => {controller.abort(); stop();};
  }, []);

  // A new sky position or mode makes the shown spectrum stale.
  const key = mode === 'demo' ? `demo:${demoTargetId}` : `${selected.ra}|${selected.dec}`;
  const pending = useRef(null);
  useEffect(() => {
    if (pending.current?.key === key) {const body = pending.current.body; pending.current = null; measure(body, pending.label); return;}
    stop(); setJob(null); setError(''); setBusy(false); setReference(null); setLabel(''); setLog(null);
    if (mode !== 'demo' || !demoTargetId) return;
    const controller = new AbortController(); run.current = controller;
    setBusy(true);
    fetchDemoSpectrum(demoTargetId, {signal: controller.signal}).then(data => {if (run.current === controller) setJob(data);})
      .catch(err => {if (run.current === controller) setError(err.message);})
      .finally(() => {if (run.current === controller) setBusy(false);});
  }, [key]);

  async function measure(body, name = '') {
    stop();
    const controller = new AbortController(); run.current = controller;
    setJob(null); setError(''); setReference(null); setBusy(true); setLabel(name);
    try {
      const id = await startSpectrum(body, {signal: controller.signal});
      for (;;) {
        const data = await fetchSpectrum(id, {signal: controller.signal});
        if (run.current !== controller) return;
        setJob(data);
        if (data.state === 'failed') throw new Error(data.message || 'The spectrum could not be measured.');
        if (data.state === 'done') break;
        await new Promise(resolve => setTimeout(resolve, POLL_MS));
        if (controller.signal.aborted) return;
      }
      if (body.ra != null) fetchReference(body, {signal: controller.signal}).then(data => {if (run.current === controller) setReference(data.photometry);}).catch(() => {});
    } catch (err) {
      if (run.current === controller && !controller.signal.aborted) setError(err.message);
    } finally {if (run.current === controller) setBusy(false);}
  }

  function guided(target) {
    if (target.moving) {measure({target: target.moving}, target.name); return;}
    const point = {ra: target.ra, dec: target.dec};
    if (point.ra === selected.ra && point.dec === selected.dec) {measure(point, target.name); return;}
    pending.current = {key: `${point.ra}|${point.dec}`, body: point}; pending.label = target.name;
    onGo(point);
  }

  const features = catalogue?.features || [];
  const analysis = job?.analysis;
  const series = useMemo(() => seasonSeries(analysis?.seasons), [analysis]);
  const good = useMemo(() => usablePoints(job?.points), [job]);
  // Until the reader chooses, use a log axis when a few points would flatten the rest on a linear one.
  const log = logChoice ?? wideRange(good);
  const z = redshift === '' ? NaN : Number(redshift);
  const lines = useMemo(() => redshiftedLines(z), [z]);
  const seasonsByIndex = new Map((analysis?.seasons || []).map(season => [season.index, season]));
  const running = busy && mode === 'live';
  const moving = job?.request.kind === 'moving' || job?.request.tracked;
  const rejected = outcomeSummary(analysis?.counts);
  const change = analysis?.variability;
  const download = () => {
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([csvOf(job)], {type: 'text/csv'}));
    link.download = `spherex-spectrum-${(job.request.name || `${job.request.ra}_${job.request.dec}`).toString().replace(/[^A-Za-z0-9._-]+/g, '-')}.csv`;
    link.click(); URL.revokeObjectURL(link.href);
  };

  return <section className="panel spectrum-panel" aria-label="Spectral fingerprint" data-testid="spectrum-panel">
    <div className="eyebrow">SPECTRAL FINGERPRINT</div>
    <h2>What is this point of sky made of?</h2>
    <p className="spectrum-lede">SPHEREx sees every point of the sky through a filter whose colour changes across the detector, so each exposure measures that point at one infrared wavelength. Measuring the same position in every exposure builds its spectrum from 0.75 to 5 µm: the range where water, carbon dioxide and carbon monoxide leave their marks, most of it invisible from the ground.</p>

    {mode === 'live' && <div className="spectrum-actions">
      <button type="button" onClick={() => measure({ra: selected.ra, dec: selected.dec})} disabled={running} data-testid="measure-spectrum">
        {running ? 'Measuring…' : `Measure the spectrum at RA ${selected.ra.toFixed(4)}°, Dec ${selected.dec.toFixed(4)}°`}</button>
      <div className="spectrum-guided"><span>Or start with a target whose answer is known:</span>
        {GUIDED_TARGETS.map(target => <button type="button" className="secondary" key={target.id} disabled={running} onClick={() => guided(target)} title={target.look}>{target.name}</button>)}
      </div>
    </div>}

    {busy && <div className="download-progress" role="status" data-testid="spectrum-progress">
      <strong>{job?.total ? `Measured ${job.done} of ${job.total} exposures` : mode === 'demo' ? 'Measuring the preloaded exposures…' : 'Asking the IRSA archive which exposures cover this position…'}</strong>
      {job?.total > 0 && <div className="spectrum-progress-bar"><span style={{width: `${100 * job.done / job.total}%`}}/></div>}
      <span>{job?.total ? `${job.megabytes_read} MB read so far, instead of ${(job.total * 0.07).toFixed(0)} GB of full images. The plot fills in as exposures arrive.` : 'This first step usually takes 5 to 15 seconds.'}</span>
      {mode === 'live' && <button type="button" className="secondary" onClick={() => {stop(); setBusy(false);}}>Stop</button>}
    </div>}
    {error && <p className="error" role="alert">{error}</p>}

    {job && job.total === 0 && job.state === 'done' && <p role="status">{job.message}</p>}
    {job && job.total > 0 && <>
      <h3 className="spectrum-title" data-testid="spectrum-title">{label || job.request.name || `RA ${job.request.ra}°, Dec ${job.request.dec}°`}
        <small>{good.length} usable of {job.done} exposures{job.truncated ? ` (an even sample of the ${job.available.toLocaleString()} available)` : ''}{analysis?.median_snr != null ? ` · median signal-to-noise ${analysis.median_snr.toFixed(0)}` : ''}</small></h3>
      {moving && <p className="spectrum-note">Moving target: each exposure is measured at the position predicted for that moment ({job.request.position_source ? <a href={job.request.position_source}>IRSA table</a> : 'official prediction table'}), not at one sky position.</p>}
      {analysis?.median_snr != null && analysis.median_snr < 3 && <p className="spectrum-note">Nothing is clearly detected at this position: the points scatter around zero. These are upper limits, not a spectrum of a source.</p>}
      <SpectrumChart points={job.points} series={series} binned={analysis.binned} features={features}
        results={analysis.mixed_seasons ? [] : analysis.features} reference={reference} lines={lines} log={log} onLog={setLog}/>
      {rejected.length > 0 && <p className="spectrum-rejected">Not plotted: {rejected.join(', ')}.{analysis.counts.saturated > job.done / 4 ? ' This source is too bright for SPHEREx at some wavelengths.' : ''}</p>}

      <div className="spectrum-columns">
        <div>
          <h3>Bands found</h3>
          {analysis.mixed_seasons ? <>
            <p className="spectrum-note">The source changed strongly between seasons, so each season is analysed on its own.</p>
            {analysis.features_by_season.map(entry => <div key={entry.index} className="spectrum-season-block">
              <h4>{seasonLabel(seasonsByIndex.get(entry.index))}</h4><Findings results={entry.features} features={features} thresholds={catalogue?.thresholds}/></div>)}
          </> : <>{analysis.seasons_scaled && <p className="spectrum-note">Seasons differ in brightness, so each was scaled to the reference season before the bands were measured. The plotted points are unscaled.</p>}
            <Findings results={analysis.features} features={features} thresholds={catalogue?.thresholds}/></>}
        </div>
        <div>
          <h3>Change between seasons</h3>
          {!change || change.status === 'not_measurable' ? <p className="spectrum-none">{analysis.seasons.length < 2 ? 'Only one observing season so far. SPHEREx returns to every point about every six months.' : 'Too few matching measurements to compare seasons.'}</p> : <>
            <p data-testid="spectrum-change" className={change.status === 'variable' ? 'spectrum-changed' : ''}>{change.status === 'variable'
              ? `Brightness changed by ${change.amplitude >= 1 ? `a factor of ${(1 + change.amplitude).toFixed(1)}` : `${Math.round(change.amplitude * 100)}%`} between seasons (${change.significance > 100 ? 'over 100' : change.significance.toFixed(0)}σ).`
              : `Steady: seasons agree within ${Math.max(1, Math.round(change.amplitude * 100))}% (changes under ${Math.round(change.floor * 100)}% are not reported).`}</p>
            <table className="spectrum-table"><thead><tr><th>Season</th><th>Relative brightness</th><th>By detector</th></tr></thead><tbody>
              {change.seasons.map(season => <tr key={season.index}><td>{seasonLabel(season)}</td>
                <td>{season.reference ? '1 (reference)' : `${season.relative_flux.toFixed(2)} ± ${season.relative_flux_err.toFixed(2)}`}</td>
                <td>{season.bands.map(band => `D${band.detector} ${band.relative_flux.toFixed(2)}`).join(' · ') || '—'}</td></tr>)}
            </tbody></table>
            <p className="spectrum-caveat">Compared at matching wavelengths only.{moving ? ' A moving target also changes distance and viewing angle between seasons.' : ' A star with fast proper motion drifts out of the fixed aperture and can mimic fading.'}</p>
          </>}
        </div>
      </div>

      <details className="spectrum-details"><summary>Redshift ruler for galaxies and quasars</summary>
        <p>Light from a distant galaxy is stretched by 1 + z. Slide z until the marked lines land on the bumps in the spectrum: that z is the redshift.</p>
        <label htmlFor="spectrum-z">Redshift z = {redshift === '' ? 'off' : Number(redshift).toFixed(3)}</label>
        <input id="spectrum-z" type="range" min="0" max="6" step="0.005" value={redshift === '' ? 0 : redshift} onChange={event => setRedshift(event.target.value)}/>
        <button type="button" className="secondary" onClick={() => setRedshift('')}>Hide lines</button>
      </details>
      <details className="spectrum-details"><summary>Table of measurements and download</summary>
        <button type="button" className="secondary" onClick={download} data-testid="spectrum-csv">Download CSV (every exposure, with rejection reasons)</button>
        <div className="spectrum-scroll"><table className="spectrum-table"><thead><tr><th>Wavelength</th><th>Flux density</th><th>Uncertainty</th><th>Date (UTC)</th><th>Detector</th><th>Exposure</th></tr></thead><tbody>
          {[...good].sort((a, b) => a.wavelength_um - b.wavelength_um).map((point, index) => <tr key={index}><td>{point.wavelength_um.toFixed(4)} µm</td><td>{formatFlux(point.flux_mjy)}</td><td>{formatFlux(point.flux_err_mjy)}</td><td>{shortDate(point.utc)}</td><td>{point.detector}</td><td>{point.obs_id}</td></tr>)}
        </tbody></table></div>
      </details>
      <details className="spectrum-details"><summary>How this was measured, and its limits</summary>
        <dl className="spectrum-method">{['source', 'photometry', 'background', 'uncertainty', 'wavelength', 'rejected'].map(name => <div key={name}><dt>{name}</dt><dd>{job.method[name]}</dd></div>)}</dl>
        <ul>{job.method.limits.map(line => <li key={line}>{line}</li>)}</ul>
        {reference?.length > 0 && <p>Open diamonds are 2MASS (1997–2001) and WISE (2010) catalogue values for the nearest source within 4″: an independent check of the flux scale, not part of the measurement.</p>}
      </details>
    </>}
  </section>;
}
