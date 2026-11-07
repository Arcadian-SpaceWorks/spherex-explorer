import { useEffect, useMemo, useState } from 'react';
import {
  chronologicalFrames,
  extractAvailableMonths,
  filterTimelineFrames,
  formatMonthDate,
  formatUtcLabel,
  isSyntheticObservation,
  timelapseFilename,
  wavelengthLabel,
} from '../timeline';
import { loadObservationImage } from '../imageAdapter';
import TimeSlider from './TimeSlider';

export default function TemporalImageExplorer({result, loading, error, target}) {
  const sequence = useMemo(() => chronologicalFrames(loading ? [] : result?.observations), [loading, result]);

  const [selectedMonthKey, setSelectedMonthKey] = useState('all');
  const [enableCadence, setEnableCadence] = useState(true);
  const [cadenceValue, setCadenceValue] = useState(6);
  const [cadenceUnit, setCadenceUnit] = useState('months');
  const [isPlaying, setIsPlaying] = useState(false);

  const availableMonths = useMemo(() => {
    // Strictly extract 6-month survey epochs when survey cadence is active
    const frames = enableCadence
      ? filterTimelineFrames(sequence.frames, { enableCadence: true, cadenceValue: 6, cadenceUnit: 'months' }).frames
      : sequence.frames;
    return extractAvailableMonths(frames);
  }, [sequence.frames, enableCadence]);

  const [timelapseState, setTimelapseState] = useState({
    loading: false,
    progress: 0,
    total: 0,
    message: '',
    error: false,
  });

  const activeSequence = useMemo(() => {
    return filterTimelineFrames(sequence.frames, {
      selectedMonthKey,
      enableCadence,
      cadenceValue,
      cadenceUnit,
    });
  }, [sequence.frames, selectedMonthKey, enableCadence, cadenceValue, cadenceUnit]);

  const signature = activeSequence.frames.map(frame => `${frame.obs_id}|${frame.observed_at_utc}|${frame.energy_bandpassname}|${frame.access_url}`).join('\n');
  const [index, setIndex] = useState(0);
  const [seen, setSeen] = useState(signature);
  const [metadata, setMetadata] = useState(null);
  const [imageError, setImageError] = useState('');
  const [imageLoading, setImageLoading] = useState(false);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [retry, setRetry] = useState(0);

  const displayIndex = !activeSequence.frames.length || seen !== signature ? 0 : Math.min(index, activeSequence.frames.length - 1);
  if (seen !== signature) {
    setSeen(signature);
    setIndex(0);
  }

  // Play / Pause slideshow timer
  useEffect(() => {
    if (!isPlaying || activeSequence.frames.length <= 1) return;
    const timer = setInterval(() => {
      setIndex(prev => (prev + 1) % activeSequence.frames.length);
    }, 1200);
    return () => clearInterval(timer);
  }, [isPlaying, activeSequence.frames.length]);

  function resetFilters() {
    setSelectedMonthKey('all');
    setEnableCadence(true);
    setCadenceValue(6);
    setCadenceUnit('months');
    setIsPlaying(false);
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
  const dateFormatted = frame ? formatMonthDate(frame.observed_at_utc) : '';

  const isUserFiltered = Boolean(selectedMonthKey !== 'all' || enableCadence);
  const selectedMonthObj = availableMonths.find(m => m.key === selectedMonthKey) || null;

  // Video Timelapse Generator
  async function generateTimelapse() {
    if (activeSequence.frames.length < 2) return;
    if (typeof MediaRecorder === 'undefined') {
      setTimelapseState({
        loading: false,
        progress: 0,
        total: 0,
        message: 'Timelapse recording is not supported in this browser.',
        error: true,
      });
      return;
    }

    setIsPlaying(false);
    setTimelapseState({
      loading: true,
      progress: 0,
      total: activeSequence.frames.length,
      message: 'Preparing timelapse video...',
      error: false,
    });

    try {
      let mimeType = 'video/webm';
      if (MediaRecorder.isTypeSupported('video/webm;codecs=vp9')) {
        mimeType = 'video/webm;codecs=vp9';
      } else if (MediaRecorder.isTypeSupported('video/webm')) {
        mimeType = 'video/webm';
      } else if (MediaRecorder.isTypeSupported('video/mp4;codecs=avc1')) {
        mimeType = 'video/mp4;codecs=avc1';
      } else if (MediaRecorder.isTypeSupported('video/mp4')) {
        mimeType = 'video/mp4';
      }

      const width = 800;
      const height = 540;
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext('2d');

      const stream = canvas.captureStream(30);
      const chunks = [];
      const recorder = new MediaRecorder(stream, {
        mimeType: mimeType || undefined,
        videoBitsPerSecond: 2500000,
      });

      recorder.ondataavailable = e => {
        if (e.data && e.data.size > 0) chunks.push(e.data);
      };

      const recordPromise = new Promise((resolve, reject) => {
        recorder.onstop = () => resolve(new Blob(chunks, { type: mimeType || 'video/webm' }));
        recorder.onerror = err => reject(err);
      });

      recorder.start();

      const frameDelay = 650;
      for (let i = 0; i < activeSequence.frames.length; i++) {
        const curFrame = activeSequence.frames[i];
        setTimelapseState(prev => ({
          ...prev,
          progress: i + 1,
          message: `Encoding frame ${i + 1} of ${activeSequence.frames.length}...`,
        }));

        let previewImg = null;
        try {
          const imgData = await loadObservationImage(curFrame, target);
          if (imgData?.preview_url) {
            previewImg = await new Promise(res => {
              const im = new Image();
              im.crossOrigin = 'anonymous';
              im.onload = () => res(im);
              im.onerror = () => res(null);
              im.src = imgData.preview_url;
            });
          }
        } catch {
          previewImg = null;
        }

        ctx.fillStyle = '#060a12';
        ctx.fillRect(0, 0, width, height);

        // Header bar
        ctx.fillStyle = '#101825';
        ctx.fillRect(0, 0, width, 48);
        ctx.fillStyle = '#80d7c2';
        ctx.font = 'bold 12px sans-serif';
        ctx.fillText('NASA SPHEREx OBSERVATION TIMELAPSE', 20, 24);

        ctx.fillStyle = '#8ea5bf';
        ctx.font = '11px monospace';
        const coordText = target ? `RA ${Number(target.ra).toFixed(3)}°  DEC ${Number(target.dec).toFixed(3)}°` : '';
        ctx.fillText(coordText, width - 210, 24);
        ctx.fillStyle = '#263143';
        ctx.fillRect(0, 48, width, 1);

        // Image Stage
        const stageX = 20;
        const stageY = 60;
        const stageW = width - 40;
        const stageH = height - 160;

        ctx.fillStyle = '#0a0f19';
        ctx.fillRect(stageX, stageY, stageW, stageH);
        ctx.strokeStyle = '#233145';
        ctx.lineWidth = 1;
        ctx.strokeRect(stageX, stageY, stageW, stageH);

        if (previewImg) {
          const scale = Math.min(stageW / previewImg.width, stageH / previewImg.height);
          const dw = previewImg.width * scale;
          const dh = previewImg.height * scale;
          const dx = stageX + (stageW - dw) / 2;
          const dy = stageY + (stageH - dh) / 2;
          ctx.drawImage(previewImg, dx, dy, dw, dh);
        } else {
          ctx.fillStyle = '#73839b';
          ctx.font = '14px sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText(`Observation ${curFrame.obs_id || 'Frame'}`, width / 2, stageY + stageH / 2);
          ctx.textAlign = 'left';
        }

        // Footer info block
        ctx.fillStyle = '#101825';
        ctx.fillRect(0, height - 90, width, 90);
        ctx.fillStyle = '#263143';
        ctx.fillRect(0, height - 90, width, 1);

        // Date and Time
        ctx.fillStyle = '#80e7ce';
        ctx.font = 'bold 18px sans-serif';
        ctx.fillText(formatMonthDate(curFrame.observed_at_utc), 20, height - 60);

        ctx.fillStyle = '#94a6bd';
        ctx.font = '12px monospace';
        ctx.fillText(formatUtcLabel(curFrame.observed_at_utc), 20, height - 38);

        // Observation details
        ctx.fillStyle = '#eef4fa';
        ctx.font = '12px sans-serif';
        ctx.fillText(`Observation ID: ${curFrame.obs_id || '—'}`, 240, height - 60);
        ctx.fillText(`Bandpass: ${curFrame.energy_bandpassname || '—'}`, 240, height - 38);

        ctx.fillText(`Wavelength: ${wavelengthLabel(curFrame)}`, 500, height - 60);
        ctx.fillStyle = '#7ed6c2';
        ctx.fillText(`Step ${i + 1} of ${activeSequence.frames.length} · 6-Month Survey Cadence`, 500, height - 38);

        await new Promise(r => setTimeout(r, frameDelay));
      }

      await new Promise(r => setTimeout(r, 600));
      recorder.stop();

      const videoBlob = await recordPromise;
      const downloadUrl = URL.createObjectURL(videoBlob);
      const filename = timelapseFilename(selectedMonthKey, target);

      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      setTimeout(() => URL.revokeObjectURL(downloadUrl), 10000);

      setTimelapseState({
        loading: false,
        progress: activeSequence.frames.length,
        total: activeSequence.frames.length,
        message: `✅ Timelapse video downloaded successfully as ${filename}!`,
        error: false,
      });
    } catch (err) {
      setTimelapseState({
        loading: false,
        progress: 0,
        total: 0,
        message: `Timelapse generation failed: ${err.message || 'Unknown error'}`,
        error: true,
      });
    }
  }

  return <section className="panel time-explorer" aria-label="Astronomical time explorer" aria-busy={loading || imageLoading}>
    <div className="section-heading">
      <div>
        <div className="eyebrow flex-eyebrow">
          <span>OBSERVATION TIME</span>
          <span className="survey-cadence-badge" title="SPHEREx surveys the entire sky every 6 months">🛰️ 6-Month Survey Cadence</span>
        </div>
        <h2>Time slider</h2>
      </div>
      <span className={`tag ${frame && metadata ? 'live' : ''}`}>{loading ? 'Waiting for search' : imageError || previewFailed ? 'Image unavailable' : frame ? (isUserFiltered ? 'Filtered sequence' : 'Archive sequence') : 'No sequence'}</span>
    </div>
    {loading ? <p className="empty" role="status">Waiting for the observation search to finish. The time slider resets for each target.</p>
      : error ? <p className="error" role="alert">No time sequence is available. {error}</p>
      : !result ? <p className="empty">Search SPHEREx observations for the selected point to build a time sequence.</p>
      : !sequence.frames.length ? <p className="empty">{result.count ? 'None of the returned observations include a usable image link.' : 'No observations were returned for this point, so there is no time sequence.'}</p>
      : <>
        <div className="time-filters" aria-label="Choose observation month and year where pictures were taken">
          {/* Observation Month & Year Selector */}
          <div className="time-filter-row">
            <div className="time-filter-field month-selector-field">
              <label htmlFor="time-filter-month">
                <span>Observation month & year (where pictures WERE taken)</span>
                <span className="date-hint">
                  {selectedMonthObj ? `${selectedMonthObj.count} photos taken` : `${availableMonths.length} survey month${availableMonths.length === 1 ? '' : 's'} available`}
                </span>
              </label>
              <div className="month-selector-controls">
                <select
                  id="time-filter-month"
                  data-testid="time-filter-month"
                  className="month-dropdown"
                  value={selectedMonthKey}
                  onChange={e => {
                    setSelectedMonthKey(e.target.value);
                    setIsPlaying(false);
                  }}
                >
                  <option value="all">All Survey Months ({sequence.frames.length} total observations)</option>
                  {availableMonths.map(m => (
                    <option key={m.key} value={m.key}>
                      {m.label} ({m.count} observations taken from {formatMonthDate(m.firstDate)} to {formatMonthDate(m.lastDate)})
                    </option>
                  ))}
                </select>

                {isUserFiltered && (
                  <button type="button" className="time-filter-reset" data-testid="time-filter-reset" onClick={resetFilters}>
                    Show all months
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Quick Month Pills */}
          <div className="month-pills-bar" aria-label="Available observation months">
            <span className="month-pills-title">Choose month:</span>
            <div className="month-pills-group" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={selectedMonthKey === 'all'}
                className={`month-pill ${selectedMonthKey === 'all' ? 'active' : ''}`}
                onClick={() => {
                  setSelectedMonthKey('all');
                  setIsPlaying(false);
                }}
              >
                <span>All Survey Months</span>
                <span className="month-pill-badge">{sequence.frames.length}</span>
              </button>
              {availableMonths.map(m => {
                const isActive = selectedMonthKey === m.key;
                return (
                  <button
                    key={m.key}
                    type="button"
                    role="tab"
                    aria-selected={isActive}
                    className={`month-pill ${isActive ? 'active' : ''}`}
                    onClick={() => {
                      setSelectedMonthKey(m.key);
                      setIsPlaying(false);
                    }}
                    title={`View ${m.count} photos taken in ${m.label}`}
                  >
                    <span>🗓️ {m.label}</span>
                    <span className="month-pill-badge">{m.count} photos</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Survey Cadence Sampling Options */}
          <div className="time-filter-row">
            <div className="time-filter-field cadence-field">
              <label htmlFor="time-filter-cadence-val">
                <span>Survey cadence sampling</span>
                <span className="cadence-status">
                  {enableCadence ? `Every ${cadenceValue} ${cadenceUnit}` : 'Showing every observation in selected period'}
                </span>
              </label>
              <div className="cadence-controls">
                <div className="time-filter-custom">
                  <input
                    id="time-filter-cadence-val"
                    data-testid="time-filter-cadence-val"
                    type="number"
                    min="1"
                    max="999"
                    value={cadenceValue}
                    disabled={!enableCadence}
                    onChange={e => {
                      setEnableCadence(true);
                      setCadenceValue(Math.max(1, Number(e.target.value) || 1));
                    }}
                  />
                  <select
                    aria-label="Cadence period unit"
                    data-testid="time-filter-cadence-unit"
                    value={cadenceUnit}
                    disabled={!enableCadence}
                    onChange={e => {
                      setEnableCadence(true);
                      setCadenceUnit(e.target.value);
                    }}
                  >
                    <option value="months">Months</option>
                    <option value="days">Days</option>
                    <option value="weeks">Weeks</option>
                    <option value="years">Years</option>
                  </select>
                </div>

                <div className="cadence-presets">
                  <button
                    type="button"
                    className={`preset-btn highlight ${enableCadence && cadenceValue === 6 && cadenceUnit === 'months' ? 'active' : ''}`}
                    onClick={() => {
                      setEnableCadence(true);
                      setCadenceValue(6);
                      setCadenceUnit('months');
                    }}
                  >
                    🛰️ 6 Months (SPHEREx Survey Cadence)
                  </button>
                  <button
                    type="button"
                    className={`preset-btn ${enableCadence && cadenceValue === 12 && cadenceUnit === 'months' ? 'active' : ''}`}
                    onClick={() => {
                      setEnableCadence(true);
                      setCadenceValue(12);
                      setCadenceUnit('months');
                    }}
                  >
                    12 Months (Annual)
                  </button>
                  <button
                    type="button"
                    className={`preset-btn ${!enableCadence ? 'active' : ''}`}
                    onClick={() => setEnableCadence(false)}
                  >
                    All Survey Dithers (Raw Observations)
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div className="time-filter-summary" data-testid="time-filter-summary">
            Showing {activeSequence.frames.length} of {sequence.frames.length} observations
            {selectedMonthObj ? ` taken in ${selectedMonthObj.label} (${formatMonthDate(selectedMonthObj.firstDate)} – ${formatMonthDate(selectedMonthObj.lastDate)})` : ' across all survey months'}
            {enableCadence ? ` · Cadence: every ${cadenceValue} ${cadenceUnit}` : ' · Showing every observation in selected month'}
          </div>
        </div>

        {!activeSequence.frames.length ? (
          <div className="empty time-filter-empty" role="status">
            <p>No observations match the selected month or cadence setting.</p>
            <button type="button" className="secondary reload-image" onClick={resetFilters}>Reset to view all observations</button>
          </div>
        ) : <>
          <div className="time-readout" aria-live="polite">
            <div className="time-date-header">
              <span className="time-date-highlight">{dateFormatted}</span>
              <span className="time-date-sub">{timeLabel}</span>
            </div>
            <p data-testid="time-slider-time" className="sr-only">{timeLabel}</p>
            <p data-testid="time-slider-id">Observation {frame.obs_id || '—'}</p>
            <p className="result-note">
              Step {displayIndex + 1} of {activeSequence.frames.length}. Each step is one observation
              {selectedMonthObj ? ` in ${selectedMonthObj.label}` : ''}
              {enableCadence ? ` (cadence: every ${cadenceValue} ${cadenceUnit})` : ''}.
            </p>
          </div>
          {isSyntheticObservation(frame, metadata) && <p className="synthetic-banner" role="note">Synthetic fixture. This image is not a live NASA observation.</p>}
          <div className="image-facts">
            <div><span>Observation date</span><strong>{dateFormatted}</strong></div>
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
          
          <TimeSlider
            count={activeSequence.frames.length}
            index={displayIndex}
            onChange={nextIndex => {
              setIsPlaying(false);
              setIndex(nextIndex);
            }}
            isPlaying={isPlaying}
            onTogglePlay={() => setIsPlaying(p => !p)}
            label={`${dateFormatted}, ${timeLabel}, ${frame.obs_id || 'observation'}`}
          />

          <div className="time-ends">
            <span>{formatMonthDate(activeSequence.frames[0].observed_at_utc)}</span>
            <span>{formatMonthDate(activeSequence.frames[activeSequence.frames.length - 1].observed_at_utc)}</span>
          </div>

          {/* Timelapse Video Download Action */}
          <div className="timelapse-actions">
            <button
              type="button"
              className="timelapse-download-btn"
              data-testid="timelapse-download-btn"
              disabled={timelapseState.loading || activeSequence.frames.length < 2}
              onClick={generateTimelapse}
            >
              {timelapseState.loading ? (
                <>
                  <span className="timelapse-spinner" aria-hidden="true">⏳</span>
                  <span>Generating Timelapse ({timelapseState.progress} / {timelapseState.total})...</span>
                </>
              ) : (
                <>
                  <span aria-hidden="true">🎬</span>
                  <span>Download Timelapse ({activeSequence.frames.length} frames · {selectedMonthObj ? selectedMonthObj.label : 'All Months'})</span>
                </>
              )}
            </button>
            {timelapseState.message && (
              <span className={`timelapse-status ${timelapseState.error ? 'error' : 'success'}`}>
                {timelapseState.message}
              </span>
            )}
          </div>

          <p className="result-note">Slider positions are ordered chronologically by archive date.{enableCadence ? ` Observations are spaced by approximately ${cadenceValue} ${cadenceUnit}.` : ' A large gap between observations is still a single step.'}</p>
          <p className="image-science-note">These are raw observation images. They are not spatially registered, and this slider does not detect moving objects or subtract frames.</p>
          {bandpasses.length > 1 && <p className="image-science-note">This sequence mixes bandpasses ({bandpasses.join(', ')}). Those images are not spectrally equivalent.</p>}
          {sequence.skippedCount > 0 && <p className="result-note">{sequence.skippedCount} observation{sequence.skippedCount === 1 ? '' : 's'} had no usable image link and {sequence.skippedCount === 1 ? 'is' : 'are'} not on the slider.</p>}
          {sequence.undatedCount > 0 && <p className="result-note">{sequence.undatedCount} observation{sequence.undatedCount === 1 ? '' : 's'} had no archive timestamp and {sequence.undatedCount === 1 ? 'is' : 'are'} placed after the dated frames.</p>}
          {metadata?.wavelength_note && <p className="result-note">{metadata.wavelength_note}</p>}
        </>}


        <footer className="time-explorer-cadence-footer" data-testid="time-explorer-cadence-footer">
          <div className="cadence-footer-content">
            <span className="cadence-footer-icon" aria-hidden="true">🛰️</span>
            <div className="cadence-footer-text">
              <h4>SPHEREx 6-Month All-Sky Survey Cadence</h4>
              <p>The SPHEREx observatory surveys the complete celestial sphere once every <strong>6 months</strong> (completing 4 full-sky spectroscopic surveys over its 2-year primary mission). Images of any single sky coordinate are collected in successive 6-month survey epochs, which is why pictures are organized by the specific months in which observations were taken.</p>
            </div>
          </div>
        </footer>
      </>}
  </section>;
}
