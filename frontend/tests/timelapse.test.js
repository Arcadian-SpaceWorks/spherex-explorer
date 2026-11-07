import test from 'node:test';
import assert from 'node:assert/strict';
import { CAVEATS, MAX_TIMELAPSE_FRAMES, exportProblem, frameLabels, supportedMimeType, timelapseFilename } from '../src/timelapse.js';

// TEST DATA: synthetic frames and prepared-image metadata.
const frame = (n, band = 'SPHEREx-D1') => ({obs_id: `SYNTHETIC-${n}`, energy_bandpassname: band, observed_at_utc: `2026-01-0${n % 9 + 1}T00:00:00`});
const webm = {isTypeSupported: type => type.startsWith('video/webm')};

test('filename names the target and date', () => {
  assert.equal(timelapseFilename({ra: 10.6847, dec: 41.2687}, new Date('2026-11-07T12:00:00Z')),
    'spherex_timelapse_ra10.685_dec41.269_2026-11-07.webm');
});

test('export needs video support, two frames and at most the frame limit', () => {
  assert.equal(supportedMimeType(webm), 'video/webm;codecs=vp9');
  assert.match(exportProblem([frame(1), frame(2)], undefined), /cannot record video/);
  assert.match(exportProblem([frame(1)], webm), /at least two/);
  assert.equal(exportProblem([frame(1), frame(2)], webm), null);
  const many = Array.from({length: MAX_TIMELAPSE_FRAMES + 1}, (_, n) => frame(n));
  assert.match(exportProblem(many, webm), /limit is 24.*Filter by detector/);
});

test('frame labels carry source, wavelength at the target and a mixed-detector warning', () => {
  const metadata = {preview_url: '/p.png', target: {status: 'inside', spectral: {wavelength_um: 0.89461}}};
  const live = frameLabels({frame: frame(1), metadata, index: 0, total: 3, target: {ra: 10.6847, dec: 41.2687}, mode: 'live', detectors: ['SPHEREx-D1']});
  assert.match(live.header, /live NASA\/IPAC IRSA data.*RA 10\.6847/);
  assert.match(live.details, /SYNTHETIC-1 · SPHEREx-D1 · λ at target 0\.8946 µm/);
  assert.equal(live.step, 'Frame 1 of 3');
  assert.equal(live.warning, null);
  assert.equal(live.missing, null);
  const demo = frameLabels({frame: frame(2, 'SPHEREx-D4'), metadata: null, index: 1, total: 3, target: null, mode: 'demo', detectors: ['SPHEREx-D1', 'SPHEREx-D4']});
  assert.match(demo.header, /preloaded real data/);
  assert.match(demo.details, /λ at target unknown/);
  assert.match(demo.warning, /Mixed detectors \(SPHEREx-D1, SPHEREx-D4\)/);
  assert.match(demo.missing, /unavailable/);
  const outside = frameLabels({frame: frame(3), metadata: {preview_url: '/p.png', target: {status: 'outside', spectral: {wavelength_um: 1}}}, index: 2, total: 3, mode: 'live', detectors: []});
  assert.match(outside.details, /λ at target unknown/);  // Never a value for a target outside the image.
});

test('the burned-in caveats say brightness is not comparable and nothing is validated', () => {
  assert.match(CAVEATS.join(' '), /own brightness scale/);
  assert.match(CAVEATS.join(' '), /not aligned/);
  assert.match(CAVEATS.join(' '), /No change or motion is validated/);
});
