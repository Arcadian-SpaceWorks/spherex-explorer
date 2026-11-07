import test from 'node:test';
import assert from 'node:assert/strict';
import { clearTargetWavelengths, recordFromMetadata, targetWavelength, wavelengthKey } from '../src/targetWavelengths.js';
import { requestComparison } from '../src/compareAdapter.js';

// TEST DATA: synthetic rows and metadata shaped like POST /api/images results.
const row = {obs_id: 'SYNTHETIC-A', energy_bandpassname: 'SPHEREx-D1', observed_at_utc: '2026-01-01T00:00:00',
  access_url: 'https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=synthetic-a'};
const other = {...row, obs_id: 'SYNTHETIC-B', access_url: 'https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=synthetic-b'};
const m31 = {ra: 10.6847, dec: 41.2687};

test('the at-target wavelength comes from the prepared image metadata', () => {
  clearTargetWavelengths();
  assert.equal(targetWavelength(row, m31), null);
  recordFromMetadata(row, m31, {target: {status: 'inside', spectral: {wavelength_um: 0.8946, bandwidth_um: 0.012}}});
  assert.deepEqual(targetWavelength(row, m31), {status: 'measured', wavelength_um: 0.8946, bandwidth_um: 0.012});
});

test('values are per target position, and outside or missing WCS is explicit', () => {
  clearTargetWavelengths();
  recordFromMetadata(row, m31, {target: {status: 'inside', spectral: {wavelength_um: 0.8946}}});
  assert.equal(targetWavelength(row, {ra: 210.8, dec: 54.3}), null);  // Another target: unknown, not reused.
  recordFromMetadata(other, m31, {target: {status: 'outside'}});
  assert.deepEqual(targetWavelength(other, m31), {status: 'outside'});
  recordFromMetadata(other, m31, {target: {status: 'inside', spectral: null}});
  assert.deepEqual(targetWavelength(other, m31), {status: 'unavailable'});
  recordFromMetadata(other, m31, {});  // No target information: nothing recorded or overwritten.
  assert.deepEqual(targetWavelength(other, m31), {status: 'unavailable'});
  assert.equal(wavelengthKey({}, m31), null);
});

test('a comparison records the wavelength at the target of both images', async () => {
  clearTargetWavelengths();
  const result = {decision: 'ACCEPT', previews: {a: '/a.png', b: '/b.png'},
    frames: [{wavelength_um: 0.8946, bandwidth_um: 0.012}, {wavelength_um: null}]};
  await requestComparison({a: row, b: other, target: m31, mode: 'time', fetchImpl: async () => ({ok: true, json: async () => result})});
  assert.equal(targetWavelength(row, m31).wavelength_um, 0.8946);
  assert.deepEqual(targetWavelength(other, m31), {status: 'unavailable'});
});
