import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { validateDemoManifest, targetCoverage, demoResult } from '../src/demoAdapter.js';
const manifest=JSON.parse(fs.readFileSync(new URL('../public/demo/manifest.json',import.meta.url)));
test('coverage counts exposure times separately from detector frames',()=>{
 const coverage=targetCoverage(manifest.targets.find(t=>t.id==='m101'));
 assert.equal(coverage.frames,3);assert.equal(coverage.epochs,2);assert.ok(coverage.days>0 && coverage.days<1);
});
test('expanded real bundle validates, orders observations and preserves release metadata',()=>{
 validateDemoManifest(manifest);
 for(const target of manifest.targets){
  const result=demoResult(target,manifest.science_note);
  assert.deepEqual(result.observations.map(r=>r.observed_at_utc),result.observations.map(r=>r.observed_at_utc).sort());
  for(const row of result.observations) if(row.demo.acquisition) assert.equal(row.obs_collection,row.demo.acquisition.data_release);
 }
});
test('manifest size is bounded and duplicate targets are rejected',()=>{
 const bad=structuredClone(manifest);bad.targets=Array(9).fill(manifest.targets[0]);assert.throws(()=>validateDemoManifest(bad));
});
