import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { validateDemoManifest, targetCoverage, targetReleases, demoResult } from '../src/demoAdapter.js';
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
test('a predicted source position must have both coordinates in range',()=>{
 // Adapt a real row structurally (no image change): a fixed-sky acquisition centred on its cutout.
 const withAcquisition=extra=>{
  const data=structuredClone(manifest);const row=data.targets[0].observations[0];const source=new URL(row.source_url);
  const [ra,dec]=source.searchParams.get('center').split(',').map(Number);
  row.acquisition={mission:'SPHEREx',data_release:'spherex_qr2',calibration:source.pathname.split('/').at(-3),ra,dec,
   position_source:'https://irsa.ipac.caltech.edu/',position_mode:'fixed-sky-region',position_note:'test validation',
   discovery_sha256:'0'.repeat(64),archive_em_min_m:1e-6,archive_em_max_m:2e-6,predicted_ra:null,predicted_dec:null,...extra};
  return data;
 };
 validateDemoManifest(withAcquisition({}));
 validateDemoManifest(withAcquisition({predicted_ra:210.81,predicted_dec:54.35}));
 assert.throws(()=>validateDemoManifest(withAcquisition({predicted_ra:210.81})),/acquisition provenance/);
 assert.throws(()=>validateDemoManifest(withAcquisition({predicted_ra:360,predicted_dec:54})),/acquisition provenance/);
});
test('releases are listed in time order of first use',()=>{
 const target={observations:[{observed_at_utc:'2026-08-16T00:00:00Z',acquisition:{data_release:'spherex_qr3'}},
  {observed_at_utc:'2025-08-15T00:00:00Z',acquisition:{data_release:'spherex_qr2'}},{observed_at_utc:'2025-08-16T00:00:00Z'}]};
 assert.deepEqual(targetReleases(target),['spherex_qr2','spherex_qr3']);
 assert.deepEqual(targetReleases({observations:[]}),[]);
});
