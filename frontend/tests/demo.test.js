import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { validateDemoManifest, demoResult, loadDemoManifest, loadDemoImage } from '../src/demoAdapter.js';
import { loadObservationImage } from '../src/imageAdapter.js';
const root = new URL('../public/', import.meta.url);
const manifest = JSON.parse(fs.readFileSync(new URL('./demo/manifest.json', root)));

test('validates real bundle and orders observations by UTC, then detector', () => {
  validateDemoManifest(manifest);
  const target = structuredClone(manifest.targets[0]);
  target.observations.reverse();
  const result = demoResult(target, manifest.science_note);
  assert.equal(result.mode, 'demo');
  assert.equal(result.observations.length, 3);
  assert.deepEqual(result.observations.map(row => row.energy_bandpassname), ['SPHEREx-D5', 'SPHEREx-D2', 'SPHEREx-D5']);
  assert.deepEqual(result.observations.map(o => o.observed_at_utc), [...result.observations.map(o => o.observed_at_utc)].sort());
  assert.deepEqual(manifest.targets.map(t => t.id), ['m101', 'm31', 'barnard', '3i-atlas']);
  const m31 = demoResult(manifest.targets[1], manifest.science_note);
  assert.equal(m31.count, 18);
  // One exposure per detector in each of three passes; same-moment frames ordered by detector.
  for (const detector of [1, 2, 3, 4, 5, 6]) assert.equal(m31.observations.filter(row => row.energy_bandpassname === `SPHEREx-D${detector}`).length, 3);
  assert.deepEqual(m31.observations.slice(0, 2).map(row => row.energy_bandpassname), ['SPHEREx-D1', 'SPHEREx-D4']);
});

test('rejects malformed versions, times, targets, sources and external asset URLs', () => {
  const changes = [
    data => {data.schema_version = 2;},
    data => {data.targets[0].ra = NaN;},
    data => {data.targets[1].id = data.targets[0].id;},
    data => {data.targets[0].observations[0].observed_at_utc = '2026-02-30T00:00:00Z';},
    data => {data.targets[0].observations[0].source_url = 'https://evil.test/a';},
    data => {data.targets[0].observations[0].preview_path = 'https://evil.test/a.png';},
    data => {data.targets[1].status = 'missing';},  // Ready target with observations claimed missing.
  ];
  for (const change of changes) {
    const data = structuredClone(manifest); change(data);
    assert.throws(() => validateDemoManifest(data));
  }
});

test('demo playback uses local metadata exclusively; live mode keeps its API', async () => {
  const calls = [];
  const result = demoResult(manifest.targets[0], manifest.science_note);
  const fetchImpl = async url => {
    calls.push(url);
    assert.ok(url.startsWith('/demo/'));
    const bytes = fs.readFileSync(new URL(`.${url}`, root));
    return {ok:true, arrayBuffer:async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset+bytes.byteLength)};
  };
  const metadata = await loadObservationImage(result.observations[0], result, {fetchImpl});
  assert.equal(metadata.demo, true);
  assert.equal(calls.length, 1);
  await loadObservationImage({access_url:'https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=x'}, {ra:10,dec:41}, {
    fetchImpl: async (url, options) => {
      assert.equal(url, '/api/images');
      assert.equal(JSON.parse(options.body).cutout_deg, .3);
      return {ok:true,json:async () => ({preview_url:'/api/images/x/preview'})};
    },
  });
});

test('missing manifest/metadata and corrupt metadata fail without live fallback', async () => {
  const absent = async () => ({ok:false});
  await assert.rejects(() => loadDemoManifest({fetchImpl:absent}), /manifest missing/);
  const observation = demoResult(manifest.targets[0], manifest.science_note).observations[0];
  await assert.rejects(() => loadDemoImage(observation, {fetchImpl:absent}), /metadata missing/);
  await assert.rejects(() => loadDemoImage(observation, {fetchImpl:async () => ({ok:true,arrayBuffer:async () => new TextEncoder().encode('{}').buffer})}), /checksum mismatch/);
});
