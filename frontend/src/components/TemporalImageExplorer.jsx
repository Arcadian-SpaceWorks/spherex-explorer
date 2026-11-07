import { useEffect, useMemo, useState } from 'react';
import { chronologicalFrames, filterTimelineFrames, formatUtcLabel, isSyntheticObservation, parsePeriodMs, wavelengthLabel } from '../timeline';
import { loadObservationImage } from '../imageAdapter';
import TimeSlider from './TimeSlider';

export default function TemporalImageExplorer({result, loading, error, target}) {
  const sequence = useMemo(() => chronologicalFrames(loading ? [] : result?.observations), [loading, result]);

  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [periodPreset, setPeriodPreset] = useState('raw');
  const [customValue, setCustomValue] = useState(3);
  const [customUnit, setCustomUnit] = useState('days');

  const periodMs = useMemo(() => {
    switch (periodPreset) {
      case '5h': return parsePeriodMs(5, 'hours');
      case '1d': return parsePeriodMs(1, 'days');
      case '3d': return parsePeriodMs(3, 'days');
      case '1w': return parsePeriodMs(1, 'weeks');
      case '1m': return parsePeriodMs(1, 'months');
      case '6y': return parsePeriodMs(6, 'years');
      case 'custom': return parsePeriodMs(customValue, customUnit);
      default: return 0;
    }
  }, [periodPreset, customValue, customUnit]);

  const activeSequence = useMemo(() => {
    return filterTimelineFrames(sequence.frames, {
      startDate,
      endDate,
      periodMs,
    });
  }, [sequence.frames, startDate, endDate, periodMs]);

  const signature = activeSequence.frames.map(frame => `${frame.obs_id}|${frame.observed_at_utc}|${frame.energy_bandpassname}|${frame.access_url}`).join('\n');
  const [index, setIndex] = useState(0);
  const [seen, setSeen] = useState(signature);
  const [metadata, setMetadata] = useState(null);
  const [imageError, setImageError] = useState('');
  const [imageLoading, setImageLoading] = useState(false);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const displayIndex = !activeSequence.frames.length || seen !== signature ? 0 : Math.min(index, activeSequence.frames.length - 1);
  if (seen !== signature) {setSeen(signature); setIndex(0);}

  function resetFilters() {
    setStartDate('');
    setEndDate('');
    setPeriodPreset('raw');
    setCustomValue(3);
    setCustomUnit('days');
  }

  const frame = activeSequence.frames[displayIndex] || null;
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

  const bandpasses = [...new Set(activeSequence.frames.map(item => item.energy_bandpassname).filter(Boolean))];
  const timeLabel = frame ? formatUtcLabel(frame.observed_at_utc) : '';

  const archiveStart = sequence.frames[0]?.observed_at_utc;
  const archiveEnd = sequence.frames[sequence.frames.length - 1]?.observed_at_utc;

  const cadenceLabel = useMemo(() => {
    switch (periodPreset) {
      case '5h': return '5 hours';
      case '1d': return '1 day';
      case '3d': return '3 days';
      case '1w': return '1 week';
      case '1m': return '1 month';
      case '6y': return '6 years';
      case 'custom': return `${customValue} ${customUnit}`;
      default: return null;
    }
  }, [periodPreset, customValue, customUnit]);

  return <section className="panel time-explorer" aria-label="Astronomical time explorer" aria-busy={loading || imageLoading}>
    <div className="section-heading"><div><div className="eyebrow">OBSERVATION TIME</div><h2>Time slider</h2></div><span className={`tag ${frame && metadata ? 'live' : ''}`}>{loading ? 'Waiting for search' : imageError || previewFailed ? 'Image unavailable' : frame ? (activeSequence.isFiltered ? 'Filtered sequence' : 'Archive sequence') : 'No sequence'}</span></div>
    {loading ? <p className="empty" role="status">Waiting for the observation search to finish. The time slider resets for each target.</p>
      : error ? <p className="error" role="alert">No time sequence is available. {error}</p>
      : !result ? <p className="empty">Search SPHEREx observations for the selected point to build a time sequence.</p>
      : !sequence.frames.length ? <p className="empty">{result.count ? 'None of the returned observations include a usable image link.' : 'No observations were returned for this point, so there is no time sequence.'}</p>
      : <>
        <div className="time-filters" aria-label="Time slider date range and cadence">
          <div className="time-filter-field">
            <label htmlFor="time-filter-start">Start date <span>UTC</span></label>
            <input id="time-filter-start" data-testid="time-filter-start" type="date" value={startDate}
              min={archiveStart ? archiveStart.slice(0, 10) : undefined}
              max={endDate || (archiveEnd ? archiveEnd.slice(0, 10) : undefined)}
              onChange={e => setStartDate(e.target.value)} />
          </div>
          <div className="time-filter-field">
            <label htmlFor="time-filter-end">End date <span>UTC</span></label>
            <input id="time-filter-end" data-testid="time-filter-end" type="date" value={endDate}
              min={startDate || (archiveStart ? archiveStart.slice(0, 10) : undefined)}
              max={archiveEnd ? archiveEnd.slice(0, 10) : undefined}
              onChange={e => setEndDate(e.target.value)} />
          </div>
          <div className="time-filter-field">
            <label htmlFor="time-filter-cadence">Cadence period</label>
            <select id="time-filter-cadence" data-testid="time-filter-cadence" value={periodPreset} onChange={e => setPeriodPreset(e.target.value)}>
              <option value="raw">Every observation (Raw archive)</option>
              <option value="5h">Every 5 hours</option>
              <option value="1d">Every 1 day</option>
              <option value="3d">Every 3 days</option>
              <option value="1w">Every 1 week</option>
              <option value="1m">Every 1 month</option>
              <option value="6y">Every 6 years</option>
              <option value="custom">Custom period…</option>
            </select>
          </div>
          {periodPreset === 'custom' && <div className="time-filter-field">
            <label htmlFor="time-filter-custom-val">Custom interval</label>
            <div className="time-filter-custom">
              <input id="time-filter-custom-val" data-testid="time-filter-custom-val" type="number" min="1" max="999" value={customValue}
                onChange={e => setCustomValue(Math.max(1, Number(e.target.value) || 1))} />
              <select aria-label="Custom period unit" data-testid="time-filter-custom-unit" value={customUnit} onChange={e => setCustomUnit(e.target.value)}>
                <option value="hours">Hours</option>
                <option value="days">Days</option>
                <option value="weeks">Weeks</option>
                <option value="months">Months</option>
                <option value="years">Years</option>
              </select>
            </div>
          </div>}
          {activeSequence.isFiltered && (
            <button type="button" className="time-filter-reset" data-testid="time-filter-reset" onClick={resetFilters}>Reset filters</button>
          )}
          {activeSequence.isFiltered && (
            <div className="time-filter-summary" data-testid="time-filter-summary">
              Showing {activeSequence.frames.length} of {sequence.frames.length} observations
              {cadenceLabel && ` · Cadence: ${cadenceLabel}`}
              {startDate && ` · From: ${startDate}`}
              {endDate && ` · To: ${endDate}`}
            </div>
          )}
        </div>

        {!activeSequence.frames.length ? (
          <div className="empty time-filter-empty" role="status">
            <p>No observations match the selected date window ({startDate || 'start'} to {endDate || 'end'}) or cadence interval ({cadenceLabel || 'none'}).</p>
            <button type="button" className="secondary reload-image" onClick={resetFilters}>Reset filters to view all observations</button>
          </div>
        ) : <>
          <div className="time-readout" aria-live="polite">
            <p className="time-current" data-testid="time-slider-time">{timeLabel}</p>
            <p data-testid="time-slider-id">Observation {frame.obs_id || '—'}</p>
            <p className="result-note">Step {displayIndex + 1} of {activeSequence.frames.length}. Each step is one observation{activeSequence.isFiltered && cadenceLabel ? ` (cadence interval: ~${cadenceLabel})` : ', not an equal interval of time'}.</p>
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
          {metadata?.observed_at_utc && metadata.observed_at_utc !== frame.observed_at_utc && <p className="result-note">FITS header time differs from the archive timestamp: {formatUtcLabel(metadata.observed_at_utc)}.</p>}
          <div className="time-stage">
            {imageLoading && <p className="image-loading" role="status">Loading the observation image for {frame.obs_id || 'this step'}.</p>}
            {imageError && <p className="image-loading error" role="alert">{imageError}</p>}
            {metadata?.preview_url && !previewFailed && <img data-testid="time-slider-image" src={metadata.preview_url} alt={`${frame.obs_id || 'SPHEREx observation'} at ${timeLabel}`} onError={() => setPreviewFailed(true)}/>}
            {previewFailed && <p className="image-loading error" role="alert">The preview image failed to load. Choose another observation or retry this one.</p>}
          </div>
          {(imageError || previewFailed) && !imageLoading && <button type="button" className="secondary reload-image" onClick={() => setRetry(count => count + 1)}>Retry this observation image</button>}
          <TimeSlider count={activeSequence.frames.length} index={displayIndex} onChange={setIndex} label={`${timeLabel}, ${frame.obs_id || 'observation'}`}/>
          <div className="time-ends"><span>{formatUtcLabel(activeSequence.frames[0].observed_at_utc)}</span><span>{formatUtcLabel(activeSequence.frames[activeSequence.frames.length - 1].observed_at_utc)}</span></div>
          <p className="result-note">Slider positions are ordered by archive time.{activeSequence.isFiltered && cadenceLabel ? ` Observations are spaced by at least ${cadenceLabel}.` : ' A large gap between observations is still a single step.'}</p>
          <p className="image-science-note">These are raw observation images. They are not spatially registered, and this slider does not detect moving objects or subtract frames.</p>
          {bandpasses.length > 1 && <p className="image-science-note">This sequence mixes bandpasses ({bandpasses.join(', ')}). Those images are not spectrally equivalent.</p>}
          {sequence.skippedCount > 0 && <p className="result-note">{sequence.skippedCount} observation{sequence.skippedCount === 1 ? '' : 's'} had no usable image link and {sequence.skippedCount === 1 ? 'is' : 'are'} not on the slider.</p>}
          {sequence.undatedCount > 0 && <p className="result-note">{sequence.undatedCount} observation{sequence.undatedCount === 1 ? '' : 's'} had no archive timestamp and {sequence.undatedCount === 1 ? 'is' : 'are'} placed after the dated frames.</p>}
          {metadata?.wavelength_note && <p className="result-note">{metadata.wavelength_note}</p>}
        </>}
      </>}
  </section>;
}
