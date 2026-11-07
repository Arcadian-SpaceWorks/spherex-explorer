/**
 * Time-lapse video export for the time slider (ported from Danae's feature/time-slider work).
 *
 * Every frame carries its own labels and the scientific caveats, burned into the video, because a
 * shared clip leaves the app and its notes behind: frames have independent brightness scales, keep
 * native detector orientation (not registered) and may mix detectors. No change or motion is claimed.
 */
import { formatUtcLabel } from './timeline.js';

export const MAX_TIMELAPSE_FRAMES = 24;  // Each live frame may need a 20-60 s download.
export const FRAME_MS = 1000;
export const SIZE = {width: 800, height: 600};
export const CAVEATS = [
  'Each frame uses its own brightness scale: brightness is not comparable between frames.',
  'Native detector orientation, not aligned: positions are not registered. No change or motion is validated.',
];

export function timelapseFilename(target, now = new Date()) {
  const stamp = now.toISOString().slice(0, 10);
  const position = target ? `_ra${Number(target.ra).toFixed(3)}_dec${Number(target.dec).toFixed(3)}` : '';
  return `spherex_timelapse${position}_${stamp}.webm`;
}

export function supportedMimeType(recorder = globalThis.MediaRecorder) {
  if (!recorder?.isTypeSupported) return null;
  return ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].find(type => recorder.isTypeSupported(type)) || null;
}

/** Why the sequence cannot be exported, or null if it can. */
export function exportProblem(frames, recorder = globalThis.MediaRecorder) {
  if (!supportedMimeType(recorder)) return 'This browser cannot record video (MediaRecorder with WebM is unavailable).';
  if (frames.length < 2) return 'A time-lapse needs at least two observations.';
  if (frames.length > MAX_TIMELAPSE_FRAMES) {
    return `This sequence has ${frames.length} observations; the limit is ${MAX_TIMELAPSE_FRAMES} because each live frame needs a download. Filter by detector or choose a smaller search.`;
  }
  return null;
}

/** Text drawn on one frame. metadata is the prepared image (null if it failed to load). */
export function frameLabels({frame, metadata, index, total, target, mode, detectors}) {
  const spectral = metadata?.target?.status === 'inside' ? metadata.target.spectral : null;
  return {
    header: `NASA SPHEREx · ${mode === 'demo' ? 'preloaded real data' : 'live NASA/IPAC IRSA data'}`
      + (target ? ` · target RA ${Number(target.ra).toFixed(4)}°, Dec ${Number(target.dec).toFixed(4)}°` : ''),
    time: formatUtcLabel(frame.observed_at_utc),
    details: [`Observation ${frame.obs_id || '—'}`, frame.energy_bandpassname || 'detector unknown',
      spectral ? `λ at target ${Number(spectral.wavelength_um).toFixed(4)} µm` : 'λ at target unknown'].join(' · '),
    step: `Frame ${index + 1} of ${total}`,
    warning: detectors.length > 1 ? `Mixed detectors (${detectors.join(', ')}): frames are at different wavelengths.` : null,
    missing: metadata?.preview_url ? null : 'Image unavailable for this observation',
  };
}

function drawFrame(ctx, image, labels) {
  const {width, height} = SIZE;
  ctx.fillStyle = '#060a12'; ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = '#101825'; ctx.fillRect(0, 0, width, 40);
  ctx.fillStyle = '#80d7c2'; ctx.font = 'bold 13px sans-serif'; ctx.textBaseline = 'middle';
  ctx.fillText(labels.header, 16, 20);
  const stage = {x: 16, y: 52, w: width - 32, h: height - 52 - 150};
  ctx.fillStyle = '#03060c'; ctx.fillRect(stage.x, stage.y, stage.w, stage.h);
  if (image) {
    const scale = Math.min(stage.w / image.width, stage.h / image.height);
    const w = image.width * scale, h = image.height * scale;
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(image, stage.x + (stage.w - w) / 2, stage.y + (stage.h - h) / 2, w, h);
  } else {
    ctx.fillStyle = '#94a3b9'; ctx.font = '15px sans-serif'; ctx.textAlign = 'center';
    ctx.fillText(labels.missing || 'Image unavailable', width / 2, stage.y + stage.h / 2); ctx.textAlign = 'left';
  }
  let y = height - 132;
  ctx.fillStyle = '#eef4fa'; ctx.font = 'bold 20px sans-serif'; ctx.fillText(labels.time, 16, y);
  ctx.fillStyle = '#80e7ce'; ctx.font = '13px sans-serif'; ctx.textAlign = 'right'; ctx.fillText(labels.step, width - 16, y); ctx.textAlign = 'left';
  y += 26; ctx.fillStyle = '#c9d6e6'; ctx.font = '14px sans-serif'; ctx.fillText(labels.details, 16, y);
  if (labels.warning) {y += 22; ctx.fillStyle = '#f5d48f'; ctx.fillText(labels.warning, 16, y);}
  ctx.fillStyle = '#2a2310'; ctx.fillRect(0, height - 54, width, 54);
  ctx.fillStyle = '#f5d48f'; ctx.font = '12px sans-serif';
  CAVEATS.forEach((line, i) => ctx.fillText(line, 16, height - 38 + i * 20));
}

function loadPicture(url) {
  return new Promise(resolve => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => resolve(null);
    image.src = url;
  });
}

/**
 * Record the frames into a WebM Blob. loadImage(frame) returns prepared image metadata (the app's
 * loadObservationImage). onProgress(i, total) reports each frame; signal cancels.
 */
export async function recordTimelapse({frames, target, mode, loadImage, onProgress = () => {}, signal}) {
  const problem = exportProblem(frames);
  if (problem) throw new Error(problem);
  const canvas = document.createElement('canvas');
  Object.assign(canvas, SIZE);
  const ctx = canvas.getContext('2d');
  const mimeType = supportedMimeType();
  const recorder = new MediaRecorder(canvas.captureStream(30), {mimeType, videoBitsPerSecond: 2_500_000});
  const chunks = [];
  recorder.ondataavailable = event => {if (event.data?.size) chunks.push(event.data);};
  const stopped = new Promise((resolve, reject) => {recorder.onstop = resolve; recorder.onerror = event => reject(event.error);});
  const detectors = [...new Set(frames.map(frame => frame.energy_bandpassname).filter(Boolean))];
  // Load every frame before recording, so slow downloads do not stretch the video.
  const prepared = [];
  for (const [index, frame] of frames.entries()) {
    if (signal?.aborted) throw new DOMException('Export cancelled', 'AbortError');
    onProgress(index + 1, frames.length);
    let metadata = null;
    try {metadata = await loadImage(frame, {signal});} catch (err) {if (err?.name === 'AbortError') throw err;}
    prepared.push({metadata, image: metadata?.preview_url ? await loadPicture(metadata.preview_url) : null,
      labels: frameLabels({frame, metadata, index, total: frames.length, target, mode, detectors})});
  }
  recorder.start(250);
  for (const item of prepared) {
    if (signal?.aborted) {recorder.stop(); throw new DOMException('Export cancelled', 'AbortError');}
    // Redraw during the frame's time so the stream keeps producing video frames.
    const end = performance.now() + FRAME_MS;
    while (performance.now() < end) {
      drawFrame(ctx, item.image, item.labels);
      await new Promise(resolve => setTimeout(resolve, 100));
    }
  }
  recorder.stop();
  await stopped;
  return new Blob(chunks, {type: mimeType});
}
