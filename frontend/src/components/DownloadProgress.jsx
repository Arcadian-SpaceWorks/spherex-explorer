import { useEffect, useState } from 'react';

// The server answers POST /api/images only when the whole file is ready, so there is no byte
// progress to report. Stages and the bar are an estimate from elapsed time against the
// typical duration; the panel says so, and never reaches 100% before the server answers.
const STAGES = [
  {label: 'Contacting IRSA', until: .12},
  {label: 'Downloading FITS', until: .7},
  {label: 'Reading headers and WCS', until: .88},
  {label: 'Rendering preview', until: Infinity},
];

export const formatElapsed = seconds => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;

/** Seconds since `runKey` last changed; pass null while idle. A new key restarts the clock. */
export function useElapsed(runKey) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    setElapsed(0);
    if (runKey == null) return undefined;
    const started = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(id);
  }, [runKey]);
  return elapsed;
}

export default function DownloadProgress({title, expectedSeconds, elapsed, queued = false, onCancel}) {
  const ratio = elapsed / expectedSeconds;
  const percent = Math.round(95 * (1 - Math.exp(-1.6 * ratio)));
  const current = queued ? -1 : STAGES.findIndex(stage => ratio < stage.until);
  const slow = !queued && ratio > 1.5;
  return <div className="download-progress" role="status" aria-live="polite" data-testid="download-progress">
    <div className="download-progress-head">
      <strong>{title}</strong>
      <span className="download-progress-time" data-testid="download-elapsed">{formatElapsed(elapsed)} elapsed · usually ~{expectedSeconds >= 90 ? `${Math.round(expectedSeconds / 60)} min` : `${expectedSeconds} s`}</span>
    </div>
    <div className="download-progress-bar" role="progressbar" aria-label="Estimated download progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={queued ? 0 : percent}>
      <span className={queued ? 'indeterminate' : ''} style={queued ? undefined : {width: `${percent}%`}}/>
    </div>
    <ol className="download-stages">
      {queued && <li className="active">Waiting for the image server (another file is being processed)</li>}
      {STAGES.map((stage, i) => <li key={stage.label} className={i < current ? 'done' : i === current ? 'active' : ''}>{stage.label}</li>)}
    </ol>
    <p className="download-progress-note">{slow
      ? 'This is taking longer than usual. IRSA may be busy; you can keep waiting or cancel.'
      : 'Progress is estimated. The image will appear here as soon as it is ready; you can keep exploring the page meanwhile.'}</p>
    {onCancel && <button type="button" className="secondary download-cancel" onClick={onCancel}>Cancel download</button>}
  </div>;
}

/** Shown when the user tries an action that would abandon a download still in progress. */
export function PendingSwitchNotice({what, elapsed, onKeepWaiting, onConfirm}) {
  return <div className="pending-switch" role="alertdialog" aria-label="Image still downloading" data-testid="pending-switch">
    <p><strong>The current image has not finished downloading</strong> ({formatElapsed(elapsed)} so far). {what} will cancel it, and you will have to wait again to see it.</p>
    <div className="pending-switch-actions">
      <button type="button" onClick={onKeepWaiting}>Keep waiting</button>
      <button type="button" className="secondary" onClick={onConfirm}>Cancel and continue</button>
    </div>
  </div>;
}
