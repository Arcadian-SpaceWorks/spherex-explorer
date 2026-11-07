import test from 'node:test';
import assert from 'node:assert/strict';
import { bandsForWavelength, filterLabel, filterParams, parseWavelength } from '../src/wavelengths.js';

test('parses wavelengths in µm, accepting a decimal comma', () => {
  assert.deepEqual(parseWavelength('2.5'), {value: 2.5});
  assert.deepEqual(parseWavelength(' 1,25 '), {value: 1.25});
  for (const bad of ['', 'abc', '0.2', '6', 'Infinity']) assert.ok(parseWavelength(bad).error, bad);
});

test('maps a wavelength to the detectors that cover it', () => {
  assert.deepEqual(bandsForWavelength(2.5), ['SPHEREx-D4']);
  assert.deepEqual(bandsForWavelength(1.11), ['SPHEREx-D1', 'SPHEREx-D2']);
  assert.deepEqual(bandsForWavelength(6), []);
});

test('builds observation query parameters from the filter', () => {
  assert.deepEqual(filterParams({band: '', wavelength: ''}), {params: {}});
  assert.deepEqual(filterParams({band: 'SPHEREx-D3', wavelength: ''}), {params: {band: 'SPHEREx-D3'}});
  assert.deepEqual(filterParams({band: '', wavelength: '3.1'}), {params: {wavelength_um: '3.1'}});
  assert.ok(filterParams({band: '', wavelength: '9'}).error);
  assert.ok(filterParams({band: '', wavelength: '', custom: true}).error);
});

test('labels the filter a result was searched with', () => {
  assert.equal(filterLabel({}), 'all wavelengths');
  assert.equal(filterLabel({band: 'SPHEREx-D2'}), 'SPHEREx-D2 only (1.10–1.65 µm)');
  assert.equal(filterLabel({wavelength_um: 2.5}), 'images covering 2.5 µm');
});
