// Adapted from contributor tests; detector IDs do not imply exact wavelengths.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { parseWavelength, filterParams, filterLabel, filterDemoResult, wavelengthCoverage } from '../src/wavelengths.js';
import { demoResult } from '../src/demoAdapter.js';

test('parses micrometres and decimal commas; rejects invalid inputs', () => {
  assert.deepEqual(parseWavelength('2.5'),{value:2.5});
  assert.deepEqual(parseWavelength(' 1,25 '),{value:1.25});
  for (const value of ['','foo','NaN','Infinity','0.2','6','0x2']) assert.ok(parseWavelength(value).error);
});

test('validates detector selection and creates archive query parameters', () => {
  assert.deepEqual(filterParams({band:'',wavelength:''}),{params:{}});
  assert.deepEqual(filterParams({band:'SPHEREx-D3',wavelength:''}),{params:{band:'SPHEREx-D3'}});
  assert.deepEqual(filterParams({band:'',wavelength:'3.1'}),{params:{wavelength_um:'3.1'}});
  assert.ok(filterParams({band:'fake',wavelength:''}).error);
  assert.ok(filterParams({band:'',wavelength:'',custom:true}).error);
  assert.equal(filterLabel({band:'SPHEREx-D2'}),'SPHEREx-D2 detector only');
});

test('inclusive coverage uses metre metadata; unknown and invalid bounds stay visible', () => {
  assert.equal(wavelengthCoverage({em_min:2.5e-6,em_max:3e-6},2.5),'range_includes');
  assert.equal(wavelengthCoverage({em_min:2e-6,em_max:2.5e-6},2.5),'range_includes');
  assert.equal(wavelengthCoverage({em_min:1e-6,em_max:2e-6},2.5),'range_excludes');
  for (const row of [{},{em_min:null,em_max:3e-6},{em_min:3e-6,em_max:2e-6},{em_min:0,em_max:3e-6}]) assert.equal(wavelengthCoverage(row,2.5),'unknown');
});

test('real M101 demo uses actual detector IDs and retains unknown spectral coverage', () => {
  const manifest=JSON.parse(fs.readFileSync(new URL('../public/demo/manifest.json',import.meta.url)));
  const source=demoResult(manifest.targets[0],manifest.science_note);
  const detector=filterDemoResult(source,{band:'SPHEREx-D5'});
  assert.equal(detector.count,2);
  assert.deepEqual(detector.observations.map(row=>row.observed_at_utc),['2026-05-22T19:40:19.088Z','2026-05-22T19:42:28.021Z']);
  const wavelength=filterDemoResult(source,{wavelength_um:'2.5'});
  assert.equal(wavelength.count,3);
  assert.equal(wavelength.unknown_wavelength_count,3);
  assert.equal(source.observations.length,3); // filtering does not mutate original inventory
});
