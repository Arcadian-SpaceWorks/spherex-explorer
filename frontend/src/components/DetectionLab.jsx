import {useState} from 'react';
export default function DetectionLab() {
  const [experiment,setExperiment]=useState('transient'), [result,setResult]=useState(null);
  const [loading,setLoading]=useState(false),[error,setError]=useState(''),[selected,setSelected]=useState(null);
  async function run() {
    setLoading(true);setError('');setResult(null);setSelected(null);
    try {
      const response=await fetch(`/api/validation?experiment=${experiment}&seed=0`);
      const data=await response.json();
      if(!response.ok || data.context!=='synthetic_injection_validation') throw new Error(data.detail || 'Invalid validation response');
      setResult(data);
    } catch(e) {setError(e.message);} finally {setLoading(false);}
  }
  return <section className="panel" aria-label="Scientific Detection Lab" aria-busy={loading}>
    <h2>Scientific Detection Lab</h2>
    <p>Test automatic astronomical change detection using real SPHEREx backgrounds and controlled synthetic signals.</p>
    <p role="note"><strong>Validation experiment — synthetic signal injected into real SPHEREx image data.</strong> No Change adds noise only.</p>
    <label>Experiment <select value={experiment} disabled={loading} onChange={e=>{setExperiment(e.target.value);setResult(null);}}>
      <option value="brightness">Brightness Change</option><option value="transient">Synthetic Transient</option><option value="no_change">No Change</option>
    </select></label>
    <button disabled={loading} onClick={run}>{loading?'Running local experiment…':'Run validation experiment'}</button>
    {error && <p role="alert">{error}</p>}
    {result && <div data-testid="validation-result">
      <h3>{result.success?'Criteria met':'Criteria NOT met'} · {result.detection.candidates.length} candidates</h3>
      <p>{result.explanation}</p><p>Execution: {result.execution}; deterministic seed {result.seed}.</p><p>Background observation {result.background.obs_id} · {result.background.observed_at_utc} UTC. Both test arrays derive from this single observation.</p>
      <p>{result.display}</p>
      <div style={{display:'flex',flexWrap:'wrap',gap:12}}>{Object.entries(result.previews).map(([role,src])=><figure key={role} style={{margin:0,width:280,maxWidth:'100%'}}>
        <div style={{position:'relative'}}><img alt={`${role} validation image`} src={src} style={{width:'100%',display:'block'}}/>
          {role==='difference' && <svg viewBox={`0 0 ${result.shape[1]} ${result.shape[0]}`} style={{position:'absolute',inset:0,width:'100%',height:'100%'}} aria-label="Candidate overlays">
            {result.detection.candidates.map(c=><g key={c.id} onClick={()=>setSelected(c)} role="button" tabIndex={0} onKeyDown={e=>{if(e.key==='Enter')setSelected(c);}} aria-label={`Select ${c.id}`}>
              <circle cx={c.x+.5} cy={result.shape[0]-.5-c.y} r={4} fill="none" stroke={selected?.id===c.id?'yellow':'cyan'} strokeWidth="1"/>
              <text x={c.x+5} y={result.shape[0]-.5-c.y} fill="cyan" fontSize="5">{c.id}</text>
            </g>)}
          </svg>}
        </div><figcaption>{role==='original'?'Reference test image (controlled noise; brightness experiment includes a synthetic baseline source)':role==='modified'?'Modified test image':'Signed difference and candidates'}</figcaption>
      </figure>)}</div>
      <p>Injected peak change {result.injection.amplitude.toPrecision(5)} MJy/sr · recovered {result.measurements.recovered_peak?.toPrecision(5) ?? 'not available'} MJy/sr · localization error {result.measurements.localization_error_pixels?.toFixed(4) ?? 'not applicable'} px.</p>
      <p>Noise model: independent Gaussian noise σ={result.injection.noise_sigma.toPrecision(4)} MJy/sr per copy. Residual MAD noise {result.detection.statistics?.empirical_noise.toPrecision(4)} MJy/sr. Threshold {result.detection.statistics?.threshold}; minimum 3 pixels. Gaussian source σ=1.5 pixels; archive PSF not used.</p>
      <div className="table-scroll"><table><thead><tr><th>Candidate</th><th>RA / Dec ICRS</th><th>Peak MJy/sr</th><th>Empirical score</th></tr></thead><tbody>
        {result.detection.candidates.map(c=><tr key={c.id}><td><button onClick={()=>setSelected(c)}>{c.id}</button></td><td>{c.ra.toFixed(6)} / {c.dec.toFixed(6)}</td><td>{c.peak_residual.toPrecision(5)}</td><td>{c.empirical_score.toFixed(2)} (not sigma)</td></tr>)}
      </tbody></table></div>
      {selected && <p role="status">{selected.id}: ICRS {selected.ra.toFixed(6)}, {selected.dec.toFixed(6)}; {selected.pixels} pixels. Calibrated uncertainty unavailable. {selected.quality_flags.join(', ')}.</p>}
      <p>Same background isolates the algorithm; it does not reproduce independent-epoch registration, calibration, wavelength or PSF systematics. No calibrated significance, physical flux variability or transient discovery is established.</p>
    </div>}
  </section>;
}
