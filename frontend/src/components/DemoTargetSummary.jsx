import { targetCoverage, targetReleases } from '../demoAdapter.js';
const releaseName = release => release.replace('spherex_', '').toUpperCase();
export default function DemoTargetSummary({target}) {
  if (!target) return null;
  const coverage=targetCoverage(target);
  const releases=targetReleases(target);
  const predictedOnFixedSky=target.observations.some(row=>row.acquisition?.position_mode==='fixed-sky-region' && row.acquisition?.predicted_ra != null);
  return <div data-testid="demo-coverage">
    {target.id==='3i-atlas' && <p>3I/ATLAS is an interstellar comet passing through our Solar System. Explore how its position and appearance were observed over time.</p>}
    {coverage.frames > 0 && <p>{coverage.frames} prepared frames · {coverage.epochs} distinct exposure times · {coverage.days.toFixed(3)} days baseline<br/>{coverage.first} → {coverage.last} (UTC)</p>}
    {target.science_context && <p role="note">{target.id==='3i-atlas' ? 'These local observations cover 14 December 2025. Positions come from the official IRSA prediction table. Infrared appearance varies with wavelength; no calibrated activity change or independently verified comet motion is established here.' : target.science_context}</p>}
    {predictedOnFixedSky && target.id==='3i-atlas' && <p role="note">Fixed-sky playback registers the real images onto the same celestial grid; native FITS previews retain their original orientation. The marker in each frame is the source's predicted position at that exposure, not a measured position.</p>}
    {releases.length > 1 && <p role="note" data-testid="mixed-releases">Frames come from {releases.length} data releases ({releases.map(releaseName).join(', ')}). Positions can be compared across them; brightness should not be.</p>}
    {target.observations.some(row=>row.acquisition?.position_mode==='moving-target-centered') && <p role="note">Moving-target-centered tracking: each cutout uses the official predicted position for that exposure. Background displacement is not a measurement of comet motion. Native images are not registered.</p>}
    {coverage.frames > 0 && <p>Same-detector frames can still sample different wavelengths because of the linear variable filter. Preview animation alone does not establish motion or brightness variation.</p>}
  </div>;
}
