import { useEffect, useState } from 'react';

export const formatElapsed = seconds => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;

// Contributor's elapsed-time UI, using a monotonic clock. The synchronous API
// exposes neither byte progress nor processing stages; never invent percentages.
export function useElapsed(runKey) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    setElapsed(0);
    if (runKey == null) return;
    const started = performance.now();
    const timer = setInterval(() => setElapsed(Math.floor((performance.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [runKey]);
  return elapsed;
}

export default function DownloadProgress({title, elapsed, local = false, onCancel, note = null, cancelNote = null}) {
  return <div className="download-progress" role="status" aria-live="polite" data-testid="download-progress">
    <strong>{title}</strong>
    <span data-testid="download-elapsed">{formatElapsed(elapsed)} elapsed</span>
    <div className="download-progress-bar" role="progressbar" aria-label="Image preparation in progress"><span/></div>
    <p>{note || (local ? 'Loading a preserved local preview. No IRSA request is made.' : 'Waiting for IRSA or the local image service. Byte progress and completion time are unavailable.')}</p>
    {onCancel && <><button type="button" className="secondary" onClick={onCancel}>Stop waiting</button><small>{cancelNote || (local ? 'You can load this preloaded preview again.' : 'Stops this browser request. Work already started on the server may finish and be cached.')}</small></>}
  </div>;
}
