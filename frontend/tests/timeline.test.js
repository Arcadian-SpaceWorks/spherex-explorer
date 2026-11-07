import test from 'node:test';
import assert from 'node:assert/strict';
import { chronologicalFrames, formatUtcLabel, isSyntheticObservation, parseUtc, usableAccessUrl, wavelengthLabel } from '../src/timeline.js';
import { loadObservationImage } from '../src/imageAdapter.js';

const url = id => `https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=${id}`;
const row = (id, time, extra = {}) => ({obs_id: id, observed_at_utc: time, access_url: url(id), energy_bandpassname: 'SPHEREx-D1', obs_collection: 'spherex', em_min: 1e-6, em_max: 2e-6, ...extra});

test('normalizes offset timestamps to UTC and rejects impossible calendar dates', () => {
  assert.equal(formatUtcLabel('2025-03-18T23:15:30+02:00'), '2025-03-18T21:15:30.000 UTC');
  assert.equal(parseUtc('2025-03-18T23:15:30+02:00'), parseUtc('2025-03-18T21:15:30Z'));
  for (const invalid of ['2025-02-30T00:00:00', '2025-02-29T00:00:00', '2025-04-31T00:00:00', '2025-01-01T24:00:00', '2025-13-01T00:00:00', '2025-01-00T00:00:00', 'not-a-time']) {
    assert.equal(parseUtc(invalid), null, invalid);
    assert.equal(formatUtcLabel(invalid), 'Time unavailable', invalid);
  }
  assert.notEqual(parseUtc('2024-02-29T00:00:00'), null);
});

test('orders uneven real timestamps as one step each and skips unusable links', () => {
  const {frames, skippedCount, undatedCount} = chronologicalFrames([
    row('late', '2025-11-02T11:42:10.500'),
    row('missing-link', '2025-06-01T00:00:00.000', {access_url: ''}),
    row('early', '2025-01-03T04:00:00.000'),
    row('mid', '2025-01-05T04:00:00.000'),
    {obs_id: 'bad-scheme', observed_at_utc: '2025-04-01T00:00:00.000', access_url: 'javascript:alert(1)'},
    row('undated', null),
    row('same-b', '2025-01-05T04:00:00.000', {energy_bandpassname: 'SPHEREx-D3'}),
  ]);
  assert.deepEqual(frames.map(frame => frame.obs_id), ['early', 'mid', 'same-b', 'late', 'undated']);
  assert.equal(frames.length, 5);
  assert.equal(skippedCount, 2);
  assert.equal(undatedCount, 1);
  assert.ok(parseUtc('2025-11-02T11:42:10.500') - parseUtc('2025-01-05T04:00:00.000') > 200 * 86400000);
  assert.equal(formatUtcLabel('2025-01-03T04:00:00.000'), '2025-01-03T04:00:00.000 UTC');
  assert.equal(formatUtcLabel('not-a-time'), 'Time unavailable');
});

test('keeps a single dated observation and rejects non-http links', () => {
  const {frames, skippedCount} = chronologicalFrames([row('only', '2024-08-19T16:02:03.100')]);
  assert.equal(frames.length, 1);
  assert.equal(frames[0].obs_id, 'only');
  assert.equal(skippedCount, 0);
  assert.equal(usableAccessUrl('http://example.test/a'), 'http://example.test/a');
  assert.equal(usableAccessUrl('ftp://example.test/a'), null);
  assert.equal(wavelengthLabel(row('only', '2024-08-19T16:02:03.100')), '1.000 – 2.000 µm');
  assert.equal(isSyntheticObservation(row('SYNTHETIC-1', '2024-01-01T00:00:00.000', {obs_collection: 'test-only'}), null), true);
  assert.equal(isSyntheticObservation(row('2025A-001', '2024-01-01T00:00:00.000'), {observation_id: '2025A-001'}), false);
});

test('posts the existing image endpoint and refuses a missing preview', async () => {
  const calls = [];
  const observation = row('obs-7', '2025-03-18T21:15:30.000');
  const data = await loadObservationImage(observation, {ra: 210.5, dec: 54.25}, {
    fetchImpl: async (endpoint, options) => {
      calls.push({endpoint, options});
      return {ok: true, json: async () => ({preview_url: '/api/images/obs-7/preview', observation_id: 'obs-7'})};
    },
  });
  assert.equal(calls[0].endpoint, '/api/images');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.headers['X-SkyTracker-Client'], 'time-slider');
  assert.deepEqual(JSON.parse(calls[0].options.body), {access_url: observation.access_url, ra: 210.5, dec: 54.25});
  assert.equal(data.preview_url, '/api/images/obs-7/preview');

  await assert.rejects(
    () => loadObservationImage(observation, {ra: 1, dec: 2}, {fetchImpl: async () => ({ok: true, json: async () => ({observation_id: 'obs-7'})})}),
    /no preview/,
  );
  await assert.rejects(
    () => loadObservationImage(observation, {ra: 1, dec: 2}, {fetchImpl: async () => ({ok: false, json: async () => ({message: 'IRSA preview unavailable'})})}),
    /IRSA preview unavailable/,
  );
});
