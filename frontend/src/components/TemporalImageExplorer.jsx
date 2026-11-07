import { useEffect, useMemo, useState } from 'react';
import { chronologicalFrames, parseUtc, formatUtcLabel, isSyntheticObservation, wavelengthLabel } from '../timeline';
import { loadObservationImage } from '../imageAdapter';
import TimeSlider from './TimeSlider';
import DownloadProgress, { useElapsed } from './DownloadProgress';

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
  const displayIndex = !sequence.frames.length || seen !== signature ? 0 : Math.min(index, sequence.frames.length - 1);
  if (seen !== signature) {setSeen(signature); setIndex(0);}

  const frame = sequence.frames[displayIndex] || null;
  const elapsed = useElapsed(imageLoading && frame ? `${frame.access_url}|${target.ra}|${target.dec}|${retry}` : null);
  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    setMetadata(null); setImageError(''); setPreviewFailed(false);
    if (!frame) {setImageLoading(false); return () => controller.abort();}
    setImageLoading(true);
    loadObservationImage(frame, target, {signal: controller.signal})
      .then(data => {if (!cancelled) setMetadata(data);})
      .catch(err => {if (!cancelled && err?.name !== 'AbortError') setImageError(err.message || 'This observation image could not be loaded.');})
      .finally(() => {if (!cancelled) setImageLoading(false);});
    return () => {cancelled = true; controller.abort();};
  }, [frame, target, retry]);

  const bandpasses = [...new Set(sequence.frames.map(item => item.energy_bandpassname).filter(Boolean))];
  const timeLabel = frame ? formatUtcLabel(frame.observed_at_utc) : '';

  return <section className="panel time-explorer" aria-label="Astronomical time explorer" aria-busy={loading || imageLoading}>
    <div className="section-heading"><div><div className="eyebrow">OBSERVATION TIME</div><h2>Time slider</h2></div><span className={`tag ${frame && metadata ? 'live' : ''}`}>{loading ? 'Waiting for search' : imageError || previewFailed ? 'Image unavailable' : frame ? result?.mode === 'demo' ? 'Preloaded sequence' : 'Archive sequence' : 'No sequence'}</span></div>
    {loading ? <p className="empty" role="status">Waiting for the observation search to finish. The time slider resets for each target.</p>
      : error ? <p className="error" role="alert">No time sequence is available. {error}</p>
      : !result ? <p className="empty">Search SPHEREx observations for the selected point to build a time sequence.</p>
      : !sequence.frames.length ? <p className="empty">{result.count ? 'None of the returned observations include a usable image link.' : 'No observations were returned for this point, so there is no time sequence.'}</p>
      : <>
        {result?.mode === 'demo' && <p className="demo-notice" role="note">{result.science_note}</p>}
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
          <div><span>Center wavelength</span><strong>{metadata?.center?.spectral ? `${Number(metadata.center.spectral.wavelength_um).toFixed(3)} µm` : imageLoading ? 'Loading…' : '—'}</strong></div>
        </div>
        {metadata?.observed_at_utc && parseUtc(metadata.observed_at_utc) !== parseUtc(frame.observed_at_utc) && <p className="result-note">FITS header time differs from the archive timestamp: {formatUtcLabel(metadata.observed_at_utc)}.</p>}
        <div className="time-stage">
          {imageLoading && <DownloadProgress title={`Loading the observation preview for ${frame.obs_id || 'this step'}`} local={Boolean(frame.demo)} elapsed={elapsed}/>}
          {imageError && <p className="image-loading error" role="alert">{imageError}</p>}
          {metadata?.preview_url && !previewFailed && <img data-testid="time-slider-image" src={metadata.preview_url} alt={`${frame.obs_id || 'SPHEREx observation'} at ${timeLabel}`} onError={() => setPreviewFailed(true)}/>}
          {previewFailed && <p className="image-loading error" role="alert">The preview image failed to load. Choose another observation or retry this one.</p>}
        </div>
        {(imageError || previewFailed) && !imageLoading && <button type="button" className="secondary reload-image" onClick={() => setRetry(count => count + 1)}>Retry this observation image</button>}
        <TimeSlider count={sequence.frames.length} index={displayIndex} onChange={setIndex} label={`${timeLabel}, ${frame.obs_id || 'observation'}`}/>
        <div className="time-ends"><span>{formatUtcLabel(sequence.frames[0].observed_at_utc)}</span><span>{formatUtcLabel(sequence.frames[sequence.frames.length - 1].observed_at_utc)}</span></div>
        <p className="result-note">Slider positions are ordered by archive time. A large gap between observations is still a single step.</p>
        <p className="image-science-note">These are raw observation images. They are not spatially registered, and this slider does not detect moving objects or subtract frames.</p>
        {bandpasses.length > 1 && <p className="image-science-note">This sequence mixes bandpasses ({bandpasses.join(', ')}). Those images are not spectrally equivalent.</p>}
        {sequence.skippedCount > 0 && <p className="result-note">{sequence.skippedCount} observation{sequence.skippedCount === 1 ? '' : 's'} had no usable image link and {sequence.skippedCount === 1 ? 'is' : 'are'} not on the slider.</p>}
        {sequence.undatedCount > 0 && <p className="result-note">{sequence.undatedCount} observation{sequence.undatedCount === 1 ? '' : 's'} had no archive timestamp and {sequence.undatedCount === 1 ? 'is' : 'are'} placed after the dated frames.</p>}
        {metadata?.wavelength_note && <p className="result-note">{metadata.wavelength_note}</p>}
      </>}
  </section>;
}
