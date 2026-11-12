/** Reads what the server is fetching and turns one job into display text. Measured values only. */
const STAGES = {
  starting: 'Starting',
  queued: 'Waiting for a free download slot',
  searching: 'Searching the IRSA archive',
  locating: 'Finding the file at IRSA',
  cutting: 'Cutting the image around the target',
  decoding: 'Making the preview',
};

export async function fetchDownloadJobs({signal, fetchImpl = fetch} = {}) {
  const response = await fetchImpl('/api/images/progress', {signal, cache: 'no-store'});
  if (!response.ok) throw new Error('Download progress is unavailable.');
  const data = await response.json();
  return Array.isArray(data.jobs) ? data.jobs : [];
}

const megabytes = bytes => `${(bytes / 1e6).toFixed(1)} MB`;

export function describeJob(job) {
  const title = job.detail ? `${job.label} · ${job.detail}` : job.label;
  const hasTotal = job.total > 0 && job.bytes <= job.total;
  const stillDownloading = job.stage === 'downloading';
  let status = stillDownloading ? `Downloading${job.source ? ` from ${job.source}` : ''}` : (STAGES[job.stage] || 'Working');
  if (job.state === 'done') status = job.kind === 'search' ? 'Search finished' : 'Ready';
  if (job.state === 'failed') status = 'Failed';

  let amount = '';
  if (job.bytes > 0) {
    if (hasTotal && stillDownloading) amount = `${megabytes(job.bytes)} of ${megabytes(job.total)}`;
    else amount = stillDownloading ? `${megabytes(job.bytes)} so far` : `${megabytes(job.bytes)} downloaded`;
  }

  // A percentage only when the remote server stated the size; null draws the moving "no measure" bar.
  let percent = null;
  if (job.state === 'done') percent = 100;
  else if (job.state === 'active' && hasTotal) percent = Math.min(100, Math.floor(job.bytes / job.total * 100));
  return {title, status, amount, percent};
}
