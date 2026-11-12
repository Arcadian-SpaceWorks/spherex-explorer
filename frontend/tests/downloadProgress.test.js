import test from 'node:test';
import assert from 'node:assert/strict';
import { describeJob, fetchDownloadJobs } from '../src/downloadProgress.js';

const job = extra => ({label: '2026W21_2A_0213_2 · D5', detail: '0.3° cutout', kind: 'image', stage: 'downloading', source: 'AWS mirror', bytes: 0, total: null, state: 'active', ...extra});

test('a stated size gives a real percentage and amount', () => {
  const view = describeJob(job({bytes: 35800000, total: 71600000}));
  assert.equal(view.percent, 50);
  assert.equal(view.amount, '35.8 MB of 71.6 MB');
  assert.equal(view.status, 'Downloading from AWS mirror');
  assert.equal(view.title, '2026W21_2A_0213_2 · D5 · 0.3° cutout');
});

test('no stated size means no invented percentage', () => {
  const view = describeJob(job({source: 'IRSA', bytes: 2300000}));
  assert.equal(view.percent, null);
  assert.equal(view.amount, '2.3 MB so far');
});

test('stages before and after the download are named, and a finished download stays full', () => {
  assert.equal(describeJob(job({stage: 'queued'})).status, 'Waiting for a free download slot');
  assert.equal(describeJob(job({stage: 'locating', source: 'IRSA'})).percent, null);
  const cutting = describeJob(job({stage: 'cutting', bytes: 71600000, total: 71600000}));
  assert.deepEqual([cutting.status, cutting.percent, cutting.amount], ['Cutting the image around the target', 100, '71.6 MB downloaded']);
});

test('finished, failed and search rows read correctly', () => {
  assert.deepEqual([describeJob(job({state: 'done'})).status, describeJob(job({state: 'done'})).percent], ['Ready', 100]);
  const failed = describeJob(job({state: 'failed', bytes: 10, total: 100}));
  assert.deepEqual([failed.status, failed.percent], ['Failed', null]);
  const search = job({kind: 'search', label: 'Observation search', detail: null, stage: 'searching', source: 'IRSA'});
  assert.deepEqual([describeJob(search).title, describeJob(search).status], ['Observation search', 'Searching the IRSA archive']);
});

test('reads jobs without caching and rejects a failed response', async () => {
  const calls = [];
  const jobs = await fetchDownloadJobs({fetchImpl: async (url, init) => {calls.push([url, init.cache]); return {ok: true, json: async () => ({jobs: [1]})};}});
  assert.deepEqual(jobs, [1]);
  assert.deepEqual(calls, [['/api/images/progress', 'no-store']]);
  await assert.rejects(fetchDownloadJobs({fetchImpl: async () => ({ok: false})}));
});
