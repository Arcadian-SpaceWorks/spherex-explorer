import test from 'node:test';
import assert from 'node:assert/strict';
import { canPick, imageRef, detectorOf, formatSeparation, hoursApart, pairHints, requestComparison, sameObservation, suggestMode } from '../src/compareAdapter.js';

// TEST DATA: synthetic archive rows shaped like GET /api/observations results.
const row = (obs_id, band, observed_at_utc, n = obs_id) => ({obs_id, energy_bandpassname: band, observed_at_utc,
  access_url: `https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=synthetic-${n}-${band}`});
const jan = row('SYNTHETIC-JAN', 'SPHEREx-D1', '2026-01-01T06:00:12.000');
const jul = row('SYNTHETIC-JUL', 'SPHEREx-D1', '2026-07-10T00:01:31.000');
const janD4 = row('SYNTHETIC-JAN', 'SPHEREx-D4', '2026-01-01T06:00:12.000');

test('detector, separation and identity helpers', () => {
  assert.equal(detectorOf(jan), 1);
  assert.equal(detectorOf({energy_bandpassname: 'other'}), null);
  assert.ok(Math.abs(hoursApart(jan, jul) / 24 - 189.75) < .01);
  assert.equal(hoursApart(jan, {observed_at_utc: 'bad'}), null);
  assert.equal(formatSeparation(0.5), '30 min');
  assert.equal(formatSeparation(5), '5.0 h');
  assert.equal(formatSeparation(72), '3.0 days');
  assert.ok(sameObservation(jan, {...jan}));
  assert.ok(!sameObservation(jan, janD4));
  assert.ok(canPick(jan));
  assert.ok(!canPick({...jan, demo: {}}));  // A demo row needs its preloaded image ID.
  assert.ok(canPick({...jan, demo: {image_id: 'a'.repeat(64)}}));
  assert.ok(!canPick({...jan, access_url: 'not a url'}));
});

test('suggests wavelength mode only for two detectors of one exposure', () => {
  assert.equal(suggestMode(jan, jul), 'time');
  assert.equal(suggestMode(jan, janD4), 'wavelength');
  assert.equal(suggestMode({...janD4, obs_id: 'OTHER', observed_at_utc: '2026-01-01T06:40:00'}, jan), 'wavelength');
  assert.equal(suggestMode(jan, null), 'time');
});

test('early hints flag pairs the server will refuse, without deciding', () => {
  assert.deepEqual(pairHints(jan, jul, 'time'), []);
  assert.deepEqual(pairHints(jan, janD4, 'wavelength'), []);
  assert.match(pairHints(jan, janD4, 'time').join(' '), /Different detectors/);
  assert.match(pairHints(jan, jul, 'wavelength').join(' '), /Not the same exposure/);
  assert.match(pairHints(jan, {...jan}, 'time')[0], /same observation/);
});

test('requestComparison posts both access URLs and validates the response', async () => {
  let sent;
  const ok = {decision: 'ACCEPT', previews: {a: '/a.png', b: '/b.png', difference: '/d.png'}, frames: [{}, {}]};
  const fetchImpl = async (url, options) => {sent = {url, body: JSON.parse(options.body)}; return {ok: true, json: async () => ok};};
  const data = await requestComparison({a: jan, b: jul, target: {ra: 10.6847, dec: 41.2687}, mode: 'time', fetchImpl});
  assert.equal(data.decision, 'ACCEPT');
  assert.equal(sent.url, '/api/compare');
  assert.deepEqual(sent.body, {a: {access_url: jan.access_url}, b: {access_url: jul.access_url},
    ra: 10.6847, dec: 41.2687, size_deg: 0.3, mode: 'time'});
});

test('requestComparison reports server messages, validation errors and broken results', async () => {
  const reply = (status, body) => async () => ({ok: status < 400, status, json: async () => body});
  const call = fetchImpl => requestComparison({a: jan, b: jul, target: {ra: 1, dec: 2}, mode: 'time', fetchImpl});
  await assert.rejects(call(reply(422, {code: 'target_outside', message: 'The target is outside this image.'})), /outside this image/);
  await assert.rejects(call(reply(422, {detail: [{msg: 'bad mode'}]})), /refused \(bad mode\)/);
  await assert.rejects(call(reply(503, {})), /busy/);
  await assert.rejects(call(reply(200, {decision: 'MAYBE'})), /incomplete/);
  await assert.rejects(call(async () => {throw new TypeError('offline');}), /could not be reached/);
});

test('demo rows are sent as preloaded image IDs and leave the wavelength store alone', async () => {
  const demoA = {...jan, demo: {image_id: 'a'.repeat(64)}}, demoB = {...jul, demo: {image_id: 'b'.repeat(64)}};
  assert.deepEqual(imageRef(demoA), {demo_image_id: 'a'.repeat(64)});
  assert.deepEqual(imageRef(jan), {access_url: jan.access_url});
  let sent;
  const ok = {decision: 'ACCEPT', previews: {a: '/a.png', b: '/b.png', difference: '/d.png'}, frames: [{wavelength_um: 9}, {wavelength_um: 9}]};
  const fetchImpl = async (url, options) => {sent = JSON.parse(options.body); return {ok: true, json: async () => ok};};
  await requestComparison({a: demoA, b: demoB, target: {ra: 269.44623, dec: 4.76867}, mode: 'time', fetchImpl});
  assert.deepEqual([sent.a, sent.b], [{demo_image_id: 'a'.repeat(64)}, {demo_image_id: 'b'.repeat(64)}]);
});
