import { useMemo, useRef, useState } from 'react';
import { DETECTOR_BANDS, WAVELENGTH_RANGE, fluxDomain, formatFlux, formatTick, logTicks, niceTicks, shortDate, usablePoints } from '../spectrum';

const WIDTH = 960, HEIGHT = 446, MARGIN = {top: 34, right: 18, bottom: 62, left: 62};
const INNER_W = WIDTH - MARGIN.left - MARGIN.right, INNER_H = HEIGHT - MARGIN.top - MARGIN.bottom;

function Marker({shape, x, y, size = 3.6, ...rest}) {
  if (shape === 'square') return <rect x={x - size} y={y - size} width={size * 2} height={size * 2} {...rest}/>;
  if (shape === 'triangle') return <path d={`M${x},${y - size * 1.25}L${x + size * 1.15},${y + size * 0.85}L${x - size * 1.15},${y + size * 0.85}Z`} {...rest}/>;
  if (shape === 'diamond') return <path d={`M${x},${y - size * 1.3}L${x + size * 1.3},${y}L${x},${y + size * 1.3}L${x - size * 1.3},${y}Z`} {...rest}/>;
  return <circle cx={x} cy={y} r={size} {...rest}/>;
}

/* Scatter of forced-photometry points (one per exposure) with error bars, coloured by season.
   One flux axis; detected bands are shaded and labelled; hover reads out the nearest exposure. */
export default function SpectrumChart({points, series, binned, features, results, reference, lines, log, onLog}) {
  const frame = useRef(null);
  const [hover, setHover] = useState(null);
  const good = useMemo(() => usablePoints(points), [points]);
  const seriesOf = useMemo(() => {
    const map = new Map();
    series.forEach(item => item.indexes.forEach(index => map.set(index, item)));
    return map;
  }, [series]);
  const domain = useMemo(() => fluxDomain([...good, ...(reference || [])], log), [good, reference, log]);
  const x = wavelength => MARGIN.left + (wavelength - WAVELENGTH_RANGE[0]) / (WAVELENGTH_RANGE[1] - WAVELENGTH_RANGE[0]) * INNER_W;
  const y = flux => {
    const fraction = log ? (Math.log10(Math.max(flux, domain[0])) - Math.log10(domain[0])) / (Math.log10(domain[1]) - Math.log10(domain[0]))
      : (flux - domain[0]) / (domain[1] - domain[0]);
    return MARGIN.top + INNER_H * (1 - Math.min(1.02, Math.max(-0.02, fraction)));
  };
  const yTicks = log ? logTicks(domain) : niceTicks(domain);
  const detected = (results || []).filter(result => result.status === 'detected')
    .map(result => ({result, feature: features.find(feature => feature.id === result.id)})).filter(item => item.feature);
  const drawn = log ? good.filter(point => point.flux_mjy > 0) : good;
  const line = (binned || []).filter(bin => !log || bin.flux_mjy > 0);

  function move(event) {
    const box = frame.current.getBoundingClientRect();
    const px = (event.clientX - box.left) / box.width * WIDTH, py = (event.clientY - box.top) / box.height * HEIGHT;
    let best = null, bestDistance = 28 ** 2;
    for (const point of drawn) {
      const distance = (x(point.wavelength_um) - px) ** 2 + (y(point.flux_mjy) - py) ** 2;
      if (distance < bestDistance) {best = point; bestDistance = distance;}
    }
    setHover(best && {point: best, left: x(best.wavelength_um) / WIDTH * 100, top: y(best.flux_mjy) / HEIGHT * 100});
  }

  return <div className="spectrum-chart">
    <div className="spectrum-toolbar">
      <div className="spectrum-legend" aria-label="Seasons">
        {series.map(item => <span key={item.key}><svg width="14" height="14" viewBox="-7 -7 14 14" aria-hidden="true"><Marker shape={item.shape} x={0} y={0} size={4.4} fill={item.color}/></svg>{item.label} <small>· {item.measured} points</small></span>)}
        {line.length > 1 && <span><svg width="18" height="14" viewBox="0 0 18 14" aria-hidden="true"><path d="M1 7H17" stroke="#e9edf5" strokeWidth="2"/></svg>Binned mean</span>}
        {reference?.length > 0 && <span><svg width="14" height="14" viewBox="-7 -7 14 14" aria-hidden="true"><Marker shape="diamond" x={0} y={0} size={4} fill="none" stroke="#e9edf5" strokeWidth="1.5"/></svg>2MASS / WISE catalogue</span>}
      </div>
      <div className="image-mode" role="group" aria-label="Flux axis scale">
        <button type="button" className="secondary" aria-pressed={!log} onClick={() => onLog(false)}>Linear</button>
        <button type="button" className="secondary" aria-pressed={log} onClick={() => onLog(true)}>Log</button>
      </div>
    </div>
    <div className="spectrum-frame" ref={frame} onPointerMove={move} onPointerLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" data-testid="spectrum-svg"
        aria-label={`Spectrum: ${good.length} measurements from ${WAVELENGTH_RANGE[0]} to ${WAVELENGTH_RANGE[1]} micrometres. The table below lists every value.`}>
        {DETECTOR_BANDS.map(([detector, low, high]) => <g key={detector}>
          <line x1={x(low)} x2={x(low)} y1={MARGIN.top} y2={MARGIN.top + INNER_H} className="spectrum-band-edge"/>
          <text x={x((low + high) / 2)} y={MARGIN.top + INNER_H + 34} className="spectrum-band-label" textAnchor="middle">detector {detector}</text>
        </g>)}
        <line x1={x(5.0)} x2={x(5.0)} y1={MARGIN.top} y2={MARGIN.top + INNER_H} className="spectrum-band-edge"/>
        {yTicks.map(tick => <g key={tick}>
          <line x1={MARGIN.left} x2={MARGIN.left + INNER_W} y1={y(tick)} y2={y(tick)} className="spectrum-grid"/>
          <text x={MARGIN.left - 8} y={y(tick) + 4} className="spectrum-tick" textAnchor="end">{formatTick(tick)}</text>
        </g>)}
        {[1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5].map(tick => <g key={tick}>
          <line x1={x(tick)} x2={x(tick)} y1={MARGIN.top + INNER_H} y2={MARGIN.top + INNER_H + 5} className="spectrum-axis"/>
          <text x={x(tick)} y={MARGIN.top + INNER_H + 18} className="spectrum-tick" textAnchor="middle">{tick}</text>
        </g>)}
        <line x1={MARGIN.left} x2={MARGIN.left + INNER_W} y1={MARGIN.top + INNER_H} y2={MARGIN.top + INNER_H} className="spectrum-axis"/>
        <text x={MARGIN.left + INNER_W / 2} y={HEIGHT - 8} className="spectrum-axis-title" textAnchor="middle">wavelength (µm)</text>
        <text x={MARGIN.left - 50} y={MARGIN.top - 16} className="spectrum-axis-title">flux density (mJy{log ? ', log scale' : ''})</text>
        {detected.map(({result, feature}) => <g key={feature.id} data-testid={`band-${feature.id}`}>
          <rect x={x(feature.core[0])} width={x(feature.core[1]) - x(feature.core[0])} y={MARGIN.top} height={INNER_H} className="spectrum-feature"/>
          <text x={x(feature.center)} y={MARGIN.top - 6} className="spectrum-feature-label" textAnchor="middle">{feature.formula}{result.kind === 'emission' ? ' ↑' : ' ↓'}</text>
        </g>)}
        {(lines || []).map((item, index, all) => {
          // A label closer than 34 px to the previous one drops to a second row instead of overprinting it.
          const lowered = index > 0 && x(item.observed) - x(all[index - 1].observed) < 34 && !all[index - 1].lowered;
          item.lowered = lowered;
          return <g key={item.label}>
            <line x1={x(item.observed)} x2={x(item.observed)} y1={MARGIN.top + (lowered ? 25 : 12)} y2={MARGIN.top + INNER_H} className="spectrum-restline"/>
            <text x={x(item.observed)} y={MARGIN.top + (lowered ? 22 : 9)} className="spectrum-restline-label" textAnchor="middle">{item.label}</text>
          </g>;
        })}
        <g className="spectrum-errors">{drawn.map((point, index) => {
          const top = y(point.flux_mjy + point.flux_err_mjy), bottom = y(log ? Math.max(point.flux_mjy - point.flux_err_mjy, domain[0]) : point.flux_mjy - point.flux_err_mjy);
          return bottom - top > 5 ? <line key={index} x1={x(point.wavelength_um)} x2={x(point.wavelength_um)} y1={top} y2={bottom} stroke={(seriesOf.get(point.epoch) || {}).color || '#8b96a8'}/> : null;
        })}</g>
        <g>{drawn.map((point, index) => {
          const item = seriesOf.get(point.epoch) || {color: '#8b96a8', shape: 'circle'};
          return <Marker key={index} shape={item.shape} x={x(point.wavelength_um)} y={y(point.flux_mjy)} size={drawn.length > 250 ? 2.6 : 3.4} fill={item.color} className="spectrum-point"/>;
        })}</g>
        {line.length > 1 && DETECTOR_BANDS.map(([detector]) => {
          const part = line.filter(bin => bin.detector === detector);
          return part.length > 1 ? <path key={detector} d={part.map((bin, index) => `${index ? 'L' : 'M'}${x(bin.wavelength_um).toFixed(1)},${y(bin.flux_mjy).toFixed(1)}`).join('')} className="spectrum-binned"/> : null;
        })}
        {(reference || []).map(item => <g key={item.band}>
          <Marker shape="diamond" x={x(item.wavelength_um)} y={y(item.flux_mjy)} size={5.5} className="spectrum-reference"/>
          <text x={x(item.wavelength_um) + 9} y={y(item.flux_mjy) - 7} className="spectrum-reference-label">{item.band}</text>
        </g>)}
        {hover && <Marker shape="circle" x={x(hover.point.wavelength_um)} y={y(hover.point.flux_mjy)} size={7} className="spectrum-hover"/>}
        {!good.length && <text x={MARGIN.left + INNER_W / 2} y={MARGIN.top + INNER_H / 2} className="spectrum-empty" textAnchor="middle">No usable measurement yet</text>}
      </svg>
      {hover && <div className="spectrum-tooltip" role="status" style={{left: `${hover.left}%`, top: `${hover.top}%`}} data-side={hover.left > 62 ? 'left' : 'right'}>
        <strong>{formatFlux(hover.point.flux_mjy)} <small>± {formatFlux(hover.point.flux_err_mjy)}</small></strong>
        <span>{hover.point.wavelength_um.toFixed(3)} µm · detector {hover.point.detector}</span>
        <span>{shortDate(hover.point.utc)} · {hover.point.obs_id}</span>
        {hover.point.flag_names?.length > 0 && <span>Note: {hover.point.flag_names.join(', ').toLowerCase()}</span>}
      </div>}
    </div>
  </div>;
}
