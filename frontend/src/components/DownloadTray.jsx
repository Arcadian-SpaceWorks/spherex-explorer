import { useEffect, useState } from 'react';
import { describeJob, fetchDownloadJobs } from '../downloadProgress';

const ACTIVE_MS = 500, IDLE_MS = 1000, MAX_ROWS = 4;

function JobRow({job}) {
  const {title, status, amount, percent} = describeJob(job);
  const value = percent == null ? {} : {'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': percent};
  return <div className="download-job" data-testid="download-job" data-state={job.state}>
    <div className="download-job-top"><b>{title}</b>{percent != null && <span>{percent}%</span>}</div>
    <small>{status}{amount ? ` · ${amount}` : ''}</small>
    <div className="download-progress-bar" role="progressbar" aria-label={`Progress of ${title}`} {...value}>
      <span className={percent == null ? undefined : 'measured'} style={percent == null ? undefined : {width: `${percent}%`}}/>
    </div>
  </div>;
}

/** Stays on screen wherever you scroll, while the server is searching or fetching. Live Mode only. */
export default function DownloadTray({enabled}) {
  const [jobs, setJobs] = useState([]);
  useEffect(() => {
    if (!enabled) {setJobs([]); return undefined;}
    let stopped = false, timer, controller;
    async function poll() {
      let next = [];
      if (!document.hidden) {
        controller = new AbortController();
        try {next = await fetchDownloadJobs({signal: controller.signal});} catch {next = [];}
      }
      if (stopped) return;
      setJobs(current => current.length || next.length ? next : current);
      timer = setTimeout(poll, next.length ? ACTIVE_MS : IDLE_MS);
    }
    poll();
    return () => {stopped = true; clearTimeout(timer); controller?.abort();};
  }, [enabled]);
  if (!jobs.length) return null;
  const active = jobs.filter(job => job.state === 'active').length;
  return <aside className="download-tray" aria-label="Downloads" data-testid="download-tray">
    <p role="status">{active ? `${active} in progress` : 'Finished'}</p>
    {jobs.slice(0, MAX_ROWS).map(job => <JobRow key={job.id} job={job}/>)}
    {jobs.length > MAX_ROWS && <small>and {jobs.length - MAX_ROWS} more</small>}
  </aside>;
}
