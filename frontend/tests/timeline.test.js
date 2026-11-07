import test from 'node:test';
import assert from 'node:assert/strict';
import {
  chronologicalFrames,
  extractAvailableMonths,
  filterTimelineFrames,
  formatMonthDate,
  formatMonthYear,
  formatUtcLabel,
  groupFramesByMonth,
  isSyntheticObservation,
  parseBoundaryDate,
  parsePeriodMs,
  parseUtc,
  timelapseFilename,
  usableAccessUrl,
  wavelengthLabel,
} from '../src/timeline.js';
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

test('extracts available observation months where pictures were taken', () => {
  assert.equal(formatMonthDate('2026-05-22T19:40:19.000Z'), 'May 22, 2026');
  assert.equal(formatMonthYear('2026-05-22T19:40:19.000Z'), 'May 2026');

  const testFrames = [
    row('m1', '2026-05-22T10:00:00Z'),
    row('m2', '2026-05-25T11:00:00Z'),
    row('j1', '2026-06-03T12:00:00Z'),
    row('j2', '2026-06-24T15:00:00Z'),
    row('n1', '2026-11-15T09:00:00Z'),
  ];
  const months = extractAvailableMonths(testFrames);
  assert.equal(months.length, 3);
  assert.equal(months[0].label, 'May 2026');
  assert.equal(months[0].count, 2);
  assert.equal(months[0].key, '2026-05');
  assert.equal(months[1].label, 'June 2026');
  assert.equal(months[1].count, 2);
  assert.equal(months[2].label, 'November 2026');
  assert.equal(months[2].count, 1);

  // Group by month
  const groups = groupFramesByMonth(testFrames);
  assert.equal(groups.length, 3);
});

test('parses boundary dates and converts period units accurately', () => {
  const start = parseBoundaryDate('2025-01-01', false);
  const end = parseBoundaryDate('2025-01-01', true);
  assert.equal(new Date(start).toISOString(), '2025-01-01T00:00:00.000Z');
  assert.equal(new Date(end).toISOString(), '2025-01-01T23:59:59.999Z');

  // Backwards compatibility with time string
  const withTimeStart = parseBoundaryDate('2025-01-01', '14:30', false);
  const withTimeEnd = parseBoundaryDate('2025-01-01', '14:30', true);
  assert.equal(new Date(withTimeStart).toISOString(), '2025-01-01T14:30:00.000Z');
  assert.equal(new Date(withTimeEnd).toISOString(), '2025-01-01T14:30:59.999Z');

  assert.equal(parseBoundaryDate(null), null);
  assert.equal(parseBoundaryDate(''), null);

  assert.equal(parsePeriodMs(6, 'months'), Math.round(6 * 30.4375 * 86400 * 1000));
  assert.equal(parsePeriodMs(1, 'months'), Math.round(30.4375 * 86400 * 1000));
  assert.equal(parsePeriodMs(1, 'days'), 86400 * 1000);
  assert.equal(parsePeriodMs(3, 'days'), 3 * 86400 * 1000);
  assert.equal(parsePeriodMs(1, 'weeks'), 7 * 86400 * 1000);
  assert.equal(parsePeriodMs(1, 'years'), Math.round(365.25 * 86400 * 1000));
  assert.equal(parsePeriodMs(0, 'months'), 0);
  assert.equal(parsePeriodMs(-2, 'months'), 0);
  assert.equal(parsePeriodMs('invalid', 'months'), 0);
});

test('filters frames by chosen month & year where pictures were taken', () => {
  const observations = [
    // May 2026
    row('m1', '2026-05-22T04:00:00.000'),
    row('m2', '2026-05-30T04:00:00.000'),
    // June 2026
    row('j1', '2026-06-06T04:00:00.000'),
    row('j2', '2026-06-24T04:00:00.000'),
    // November 2026 (Survey 2 - ~6 months later)
    row('n1', '2026-11-20T04:00:00.000'),
  ];
  const { frames } = chronologicalFrames(observations);

  // 1. Choose May 2026
  const mayOnly = filterTimelineFrames(frames, { selectedMonthKey: '2026-05' });
  assert.equal(mayOnly.isFiltered, true);
  assert.deepEqual(mayOnly.frames.map(f => f.obs_id), ['m1', 'm2']);

  // 2. Choose June 2026
  const juneOnly = filterTimelineFrames(frames, { selectedMonthKey: '2026-06' });
  assert.equal(juneOnly.isFiltered, true);
  assert.deepEqual(juneOnly.frames.map(f => f.obs_id), ['j1', 'j2']);

  // 3. Choose Nov 2026
  const novOnly = filterTimelineFrames(frames, { selectedMonthKey: '2026-11' });
  assert.equal(novOnly.isFiltered, true);
  assert.deepEqual(novOnly.frames.map(f => f.obs_id), ['n1']);

  // 4. All survey months
  const allMonths = filterTimelineFrames(frames, { selectedMonthKey: 'all' });
  assert.equal(allMonths.isFiltered, false);
  assert.equal(allMonths.frames.length, 5);

  // 5. 6-month survey cadence sampling across all months
  const sixMonthCadence = filterTimelineFrames(frames, {
    selectedMonthKey: 'all',
    enableCadence: true,
    cadenceValue: 6,
    cadenceUnit: 'months',
  });
  assert.equal(sixMonthCadence.isFiltered, true);
  // May 2026 (first survey), Nov 2026 (second survey, 6 months later)
  assert.deepEqual(sixMonthCadence.frames.map(f => f.obs_id), ['m1', 'n1']);
});

test('generates valid and clean timelapse filenames', () => {
  assert.equal(timelapseFilename('2026-05', { ra: 210.802, dec: 54.349 }), 'spherex_timelapse_2026-05_ra210.80_dec54.35.webm');
  assert.equal(timelapseFilename('all', { ra: 100.5, dec: -20.25 }), 'spherex_timelapse_all-months_ra100.50_dec-20.25.webm');
  assert.equal(timelapseFilename(null, null), 'spherex_timelapse_all-months.webm');
});
