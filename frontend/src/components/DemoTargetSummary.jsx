import { targetCoverage } from '../demoAdapter.js';
export default function DemoTargetSummary({target}) {
  if (!target) return null;
  const coverage=targetCoverage(target);
  return <div data-testid="demo-coverage">
    {coverage.frames > 0 && <p>{coverage.frames} prepared frames · {coverage.epochs} distinct exposure times · {coverage.days.toFixed(3)} days baseline<br/>{coverage.first} → {coverage.last} (UTC)</p>}
    {target.science_context && <p role="note">{target.science_context}</p>}
    {target.observations.some(row=>row.acquisition?.position_mode==='moving-target-centered') && <p role="note">Moving-target-centered tracking: each cutout uses the official predicted position for that exposure. Background displacement is not a measurement of comet motion. Native images are not registered.</p>}
    {coverage.frames > 0 && <p>Same-detector frames can still sample different wavelengths because of the linear variable filter. Preview animation alone does not establish motion or brightness variation.</p>}
  </div>;
}
