import { useEffect, useMemo, useState } from 'react';
import {
  chronologicalFrames,
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
  const [isPlaying, setIsPlaying] = useState(false);

  const [timelapseState, setTimelapseState] = useState({
    loading: false,
    progress: 0,
    total: 0,
    message: '',
    error: false,
  });

  const signature = sequence.frames.map(frame => `${frame.obs_id}|${frame.observed_at_utc}|${frame.energy_bandpassname}|${frame.access_url}`).join('\n');
  const [index, setIndex] = useState(0);
  const [seen, setSeen] = useState(signature);
  const [metadata, setMetadata] = useState(null);
  const [imageError, setImageError] = useState('');
  const [imageLoading, setImageLoading] = useState(false);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [retry, setRetry] = useState(0);

  const displayIndex = !sequence.frames.length || seen !== signature ? 0 : Math.min(index, sequence.frames.length - 1);
  if (seen !== signature) {
    setSeen(signature);
    setIndex(0);
  }

  // Play / Pause slideshow timer
  useEffect(() => {
    if (!isPlaying || sequence.frames.length <= 1) return;
    const timer = setInterval(() => {
      setIndex(prev => (prev + 1) % sequence.frames.length);
    }, 1200);
    return () => clearInterval(timer);
  }, [isPlaying, sequence.frames.length]);

  const frame = sequence.frames[displayIndex] || null;

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
  const dateFormatted = frame ? formatMonthDate(frame.observed_at_utc) : '';

  // Video Timelapse Generator
  async function generateTimelapse() {
    if (sequence.frames.length < 2) return;
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
      total: sequence.frames.length,
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
      for (let i = 0; i < sequence.frames.length; i++) {
        const curFrame = sequence.frames[i];
        setTimelapseState(prev => ({
          ...prev,
          progress: i + 1,
          message: `Encoding frame ${i + 1} of ${sequence.frames.length}...`,
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
        ctx.fillText(`Frame ${i + 1} of ${sequence.frames.length}`, 500, height - 38);

        await new Promise(r => setTimeout(r, frameDelay));
      }

      await new Promise(r => setTimeout(r, 600));
      recorder.stop();

      const videoBlob = await recordPromise;
      const downloadUrl = URL.createObjectURL(videoBlob);
      const filename = timelapseFilename('all', target);

      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      setTimeout(() => URL.revokeObjectURL(downloadUrl), 10000);

      setTimelapseState({
        loading: false,
        progress: sequence.frames.length,
        total: sequence.frames.length,
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
        <p className="eyebrow">OBSERVATION TIME</p>
        <h2>Time slider</h2>
      </div>
      <span className={`tag ${frame && metadata ? 'live' : ''}`}>{loading ? 'Waiting for search' : imageError || previewFailed ? 'Image unavailable' : frame ? 'Archive sequence' : 'No sequence'}</span>
    </div>

    {loading ? <p className="empty" role="status">Waiting for the observation search to finish. The time slider resets for each target.</p>
      : error ? <p className="error" role="alert">No time sequence is available. {error}</p>
      : !result ? <p className="empty">Search SPHEREx observations for the selected point to build a time sequence.</p>
      : !sequence.frames.length ? <p className="empty">{result.count ? 'None of the returned observations include a usable image link.' : 'No observations were returned for this point, so there is no time sequence.'}</p>
      : <>
        {/* Prominent Observation Date & Time on Top */}
        <div className="time-readout" aria-live="polite">
          <div className="time-date-header">
            <span className="time-date-highlight">{dateFormatted}</span>
            <span className="time-date-sub">{timeLabel}</span>
          </div>
          <p data-testid="time-slider-time" className="sr-only">{timeLabel}</p>
          <p data-testid="time-slider-id">Observation {frame.obs_id || '—'}</p>
          <p className="result-note">
            Observation {displayIndex + 1} of {sequence.frames.length}
          </p>
        </div>

        {isSyntheticObservation(frame, metadata) && <p className="synthetic-banner" role="note">Synthetic fixture. This image is not a live NASA observation.</p>}

        {/* Observation Image Stage */}
        <div className="time-stage">
          {imageLoading && <p className="image-loading" role="status">Loading the observation image for {frame.obs_id || 'this step'}.</p>}
          {imageError && <p className="image-loading error" role="alert">{imageError}</p>}
          {metadata?.preview_url && !previewFailed && <img data-testid="time-slider-image" src={metadata.preview_url} alt={`${frame.obs_id || 'SPHEREx observation'} at ${timeLabel}`} onError={() => setPreviewFailed(true)}/>}
          {previewFailed && <p className="image-loading error" role="alert">The preview image failed to load. Choose another observation or retry this one.</p>}
        </div>
        {(imageError || previewFailed) && !imageLoading && <button type="button" className="secondary reload-image" onClick={() => setRetry(count => count + 1)}>Retry this observation image</button>}

        {/* Simple Time Slider */}
        <TimeSlider
          count={sequence.frames.length}
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
          <span>{formatMonthDate(sequence.frames[0].observed_at_utc)}</span>
          <span>{formatMonthDate(sequence.frames[sequence.frames.length - 1].observed_at_utc)}</span>
        </div>

        {/* Observation Facts */}
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

        {/* Video Timelapse Export */}
        {sequence.frames.length > 1 && (
          <div className="timelapse-actions">
            <button
              type="button"
              className="timelapse-download-btn"
              data-testid="timelapse-download-btn"
              disabled={timelapseState.loading}
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
                  <span>Download Timelapse ({sequence.frames.length} frames)</span>
                </>
              )}
            </button>
            {timelapseState.message && (
              <span className={`timelapse-status ${timelapseState.error ? 'error' : 'success'}`}>
                {timelapseState.message}
              </span>
            )}
          </div>
        )}

        <p className="result-note">Slider positions are ordered chronologically by archive date. A large gap between observations is still a single step.</p>
        <p className="image-science-note">These are raw observation images. They are not spatially registered, and this slider does not detect moving objects or subtract frames.</p>
        {bandpasses.length > 1 && <p className="image-science-note">This sequence mixes bandpasses ({bandpasses.join(', ')}). Those images are not spectrally equivalent.</p>}
        {sequence.skippedCount > 0 && <p className="result-note">{sequence.skippedCount} observation{sequence.skippedCount === 1 ? '' : 's'} had no usable image link and {sequence.skippedCount === 1 ? 'is' : 'are'} not on the slider.</p>}
        {sequence.undatedCount > 0 && <p className="result-note">{sequence.undatedCount} observation{sequence.undatedCount === 1 ? '' : 's'} had no archive timestamp and {sequence.undatedCount === 1 ? 'is' : 'are'} placed after the dated frames.</p>}
        {metadata?.wavelength_note && <p className="result-note">{metadata.wavelength_note}</p>}
      </>}
  </section>;
}
