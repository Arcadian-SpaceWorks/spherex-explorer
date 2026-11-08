import {test,expect} from '@playwright/test';
import fs from 'node:fs';
import {formatUtcLabel} from '../../src/timeline.js';
const manifest=JSON.parse(fs.readFileSync(new URL('../../public/demo/manifest.json',import.meta.url)));
for (const target of manifest.targets.filter(t=>t.status==='ready')) {
 test(`${target.id}: every prepared frame plays with external and live API requests blocked`,async({page})=>{
  const forbidden=[];
  await page.route('**/*',route=>{
   const url=new URL(route.request().url());
   if(!['localhost','127.0.0.1'].includes(url.hostname)||['/api/images','/api/observations'].includes(url.pathname)){
    forbidden.push(url.href);return route.abort();
   }
   return route.continue();
  });
  await page.goto('/?mode=demo');
  await page.getByLabel('Preloaded target').selectOption(target.id);
  const explorer=page.getByRole('region',{name:'Astronomical time explorer'});
  await expect(page.getByTestId('demo-coverage')).toContainText(`${target.observations.length} prepared frames`);
  for(let i=0;i<target.observations.length;i++){
   const row=target.observations[i];
   if(i) await explorer.getByRole('button',{name:'Next observation'}).click();
   const image=explorer.getByTestId('time-slider-image');
   await expect(image).toHaveAttribute('src',row.preview_path);
   await expect.poll(()=>image.evaluate(img=>img.complete&&img.naturalWidth>0)).toBe(true);
   await expect(explorer.getByTestId('time-slider-id')).toHaveText(`Observation ${row.obs_id}`);
   await expect(explorer).toContainText(formatUtcLabel(row.observed_at_utc));
   if(row.acquisition) await expect(explorer).toContainText(row.acquisition.calibration);
  }
  await expect(page.locator('.image-inspector')).toContainText(target.observations[0].obs_id);
  if(target.observations.some(row=>row.acquisition?.predicted_ra!=null)) await expect(page.getByTestId('demo-coverage')).toContainText('Fixed sky: every cutout has the same centre');
  if(target.id==='barnard') await expect(page.getByTestId('mixed-releases')).toContainText('2 data releases (QR2, QR3)');
  if(target.id==='m31') await expect(page.getByTestId('mixed-releases')).toHaveCount(0);
  expect(forbidden).toEqual([]);
 });
}
test('unprepared science candidates are clearly unavailable offline',async({page})=>{
 await page.goto('/?mode=demo');
 for(const id of ['barnard','wise0855']){
  const target=manifest.targets.find(t=>t.id===id);
  if(!target || target.status!=='missing') continue;
  await page.getByLabel('Preloaded target').selectOption(id);
  await expect(page.getByText(target.missing_reason,{exact:true})).toBeVisible();
  await expect(page.getByTestId('time-slider')).toHaveCount(0);
 }
});
