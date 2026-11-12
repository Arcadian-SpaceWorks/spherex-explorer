import { useEffect, useRef, useState } from 'react';
import { candidateFilename, formatSeparation, previewPixel, requestMeasurement } from '../compareAdapter';
import { formatUtcLabel } from '../timeline';

const fmt = (value, digits) => value == null || !Number.isFinite(value) ? '—' : Number(value).toFixed(digits);
const host = url => {try {return new URL(url).hostname;} catch {return 'the recorded source';}};

function Marker({point, size, kind, label}) {
  if (!point || !size) return null;
  return <span className={`measure-marker ${kind}`} title={label} aria-hidden="true"
    style={{left: `${(point.x + 0.5) / size * 100}%`, top: `${(point.y + 0.5) / size * 100}%`}}/>;
}

function Position({role, position}) {
  return <tr>
    <th>Position {role.toUpperCase()}</th>
    <td>RA {fmt(position.ra, 5)}°, Dec {fmt(position.dec, 5)}° ± {fmt(position.sigma_arcsec, 1)}″
      <small>{position.method} · brightest pixel {fmt(position.peak_snr, 0)}× the noise
        {position.predicted ? ` · ${fmt(position.predicted.offset_arcsec, 1)}″ from the predicted position` : ''}</small></td>
  </tr>;
}

function MeasurementResult({measurement, onDownload}) {
  const {motion, prediction, positions, candidate, warnings} = measurement;
  const hours = motion.time_hours == null ? null : Math.abs(motion.time_hours);
  const perHour = hours != null && hours < 240;
  const rate = perHour ? motion.rate_arcsec_per_hour : motion.rate_arcsec_per_year;
  const rateSigma = perHour ? motion.rate_sigma_arcsec_per_hour : motion.rate_sigma_arcsec_per_year;
  const unit = perHour ? '″ per hour' : '″ per year';
  return <div className="measure-result" data-testid="measure-result">
    <p className="measure-summary" data-testid="measure-summary">{measurement.summary}</p>
    <div className="table-scroll"><table className="compare-facts"><tbody>
      <Position role="a" position={positions.a}/>
      <Position role="b" position={positions.b}/>
      <tr><th>Shift A → B</th><td data-testid="measure-shift">{fmt(motion.shift_arcsec, 1)} ± {fmt(motion.shift_sigma_arcsec, 1)}″
        {motion.direction ? ` toward the ${motion.direction} (${fmt(motion.position_angle_deg, 0)}° east of north)` : ''}
        <small>{fmt(motion.significance, 1)} times its uncertainty</small></td></tr>
      <tr><th>Time between</th><td>{formatSeparation(hours)}</td></tr>
      <tr><th>Apparent motion</th><td data-testid="measure-rate">{rate == null ? 'Not defined: both images are from the same moment.' : `${fmt(rate, 1)} ± ${fmt(rateSigma, 1)}${unit}`}</td></tr>
      {prediction && <tr><th>Prediction</th><td data-testid="measure-prediction">{fmt(prediction.shift_arcsec, 1)}″ shift
        {prediction.position_angle_deg != null ? ` toward ${fmt(prediction.position_angle_deg, 0)}°` : ''}
        {perHour && prediction.rate_arcsec_per_hour != null ? ` · ${fmt(prediction.rate_arcsec_per_hour, 1)}″ per hour` : ''}
        {!perHour && prediction.rate_arcsec_per_year != null ? ` · ${fmt(prediction.rate_arcsec_per_year, 1)}″ per year` : ''}
        <small>From {host(prediction.source)}. Measured minus predicted: {fmt(prediction.residual_arcsec, 1)}″ ({fmt(prediction.residual_sigma, 1)}× the uncertainty).</small></td></tr>}
    </tbody></table></div>
    {warnings.length > 0 && <ul className="measure-warnings" data-testid="measure-warnings">{warnings.map(text => <li key={text}>{text}</li>)}</ul>}
    <div className="measure-candidate">
      <div><strong data-testid="candidate-id">{candidate.id}</strong><small>{candidate.id_note}</small></div>
      <button type="button" className="secondary" onClick={onDownload}>Download candidate record (JSON)</button>
    </div>
    <p className="image-science-note">{candidate.claim} Uncertainties are 1σ: pixel noise plus a per-image floor for how well two images line up ({fmt(positions.a.floor_arcsec, 1)}″ here).</p>
  </div>;
}

/** Click the same object in A and B; the server centroids both and measures the shift. */
export default function MotionMeasure({result}) {
  const size = result.grid?.shape?.[0];
  const [clicks, setClicks] = useState({a: null, b: null});
  const [measurement, setMeasurement] = useState(null), [error, setError] = useState(''), [loading, setLoading] = useState(false);
  const request = useRef(null);
  useEffect(() => () => request.current?.abort(), []);
  const next = !clicks.a ? 'a' : !clicks.b ? 'b' : null;

  async function measure(points) {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setLoading(true); setError('');
    try {
      const data = await requestMeasurement({compareId: result.compare_id, clicks: points, signal: controller.signal});
      if (request.current === controller) setMeasurement(data);
    } catch (err) {
      if (request.current === controller && err?.name !== 'AbortError') setError(err.message);
    } finally {
      if (request.current === controller) setLoading(false);
    }
  }
  function choose(role, event) {
    const points = {...clicks, [role]: previewPixel(event, event.currentTarget)};
    setClicks(points); setMeasurement(null); setError('');
    if (points.a && points.b) measure(points);
  }
  function clear() {
    request.current?.abort(); request.current = null;
    setClicks({a: null, b: null}); setMeasurement(null); setError(''); setLoading(false);
  }
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(measurement.candidate, null, 2)], {type: 'application/json'}));
    const link = Object.assign(document.createElement('a'), {href: url, download: candidateFilename(measurement.candidate)});
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <section className="motion-measure" data-testid="motion-measure" aria-label="Measure motion">
    <h3>Measure motion</h3>
    <p className="result-note" data-testid="measure-instruction">{next
      ? `Click the object in image ${next.toUpperCase()}${next === 'b' ? ' (the same object as in A)' : ''}. The app finds its centre near your click.`
      : loading ? 'Measuring both centres…' : 'Click either image again to move a point.'}</p>
    <div className="compare-side">
      {result.frames.map(frame => <figure key={frame.role} className="compare-frame">
        <div className="measure-image">
          <img src={result.previews[frame.role]} data-testid={`measure-image-${frame.role}`} onClick={event => choose(frame.role, event)}
            alt={`${frame.role.toUpperCase()} for measuring: ${frame.obs_id}, ${formatUtcLabel(frame.observed_at_utc)}, north up. Click the object.`}/>
          <Marker point={clicks[frame.role]} size={size} kind="click" label="Your click"/>
          <Marker point={measurement?.positions[frame.role]?.predicted?.preview} size={size} kind="predicted" label="Predicted position"/>
          <Marker point={measurement?.positions[frame.role]?.preview} size={size} kind="centroid" label="Measured centre"/>
        </div>
        <figcaption><b>{frame.role.toUpperCase()}</b> {formatUtcLabel(frame.observed_at_utc).replace(' UTC', '')} · {frame.band}</figcaption>
      </figure>)}
    </div>
    <p className="result-note measure-legend"><span className="measure-key click" aria-hidden="true"/>your click
      <span className="measure-key centroid" aria-hidden="true"/>measured centre
      <span className="measure-key predicted" aria-hidden="true"/>predicted position (preloaded comet and Barnard frames)</p>
    {(clicks.a || clicks.b) && <button type="button" className="secondary" onClick={clear}>Clear points</button>}
    {loading && <p role="status">Measuring both centres…</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {measurement && <MeasurementResult measurement={measurement} onDownload={download}/>}
  </section>;
}
