import {test,expect} from '@playwright/test';
import fs from 'node:fs';
const manifest=JSON.parse(fs.readFileSync(new URL('../../public/demo/manifest.json',import.meta.url)));
const comet=manifest.targets.find(t=>t.id==='3i-atlas');
test('real comet fixed-sky and prediction-centered playback and comparison work offline',async({page})=>{
  const forbidden=[];
  await page.route('**/*',route=>{
    const url=new URL(route.request().url());
    if(!['localhost','127.0.0.1'].includes(url.hostname)||['/api/images','/api/observations'].includes(url.pathname)){forbidden.push(url.href);return route.abort();}
    return route.continue();
  });
  await page.goto('/?mode=demo');await page.getByLabel('Preloaded target').selectOption('3i-atlas');
  const slider=page.getByRole('region',{name:'Astronomical time explorer'});
  const marker=slider.getByTestId('predicted-comet-marker');
  await expect(marker).toBeVisible({timeout:60000});
  const firstX=Number(await marker.getAttribute('cx'));
  await slider.getByRole('slider').fill(String(comet.observations.length-1));
  await expect(slider.getByTestId('time-slider-id')).toContainText('2025W50_2A_0712_4');
  await expect.poll(async()=>Number(await marker.getAttribute('cx')),{timeout:60000}).toBeGreaterThan(firstX+70);
  await slider.getByLabel('Comet playback view').selectOption('comet_centered');
  await expect.poll(async()=>Number(await marker.getAttribute('cx')),{timeout:60000}).toBeCloseTo(88,5);
  await expect(slider).toContainText('not a measured comet detection');
  await slider.getByRole('button',{name:'Previous observation',exact:true}).click();
  await expect(marker).toBeVisible({timeout:60000});
  await slider.getByRole('button',{name:'Play observations in time order'}).click();
  await expect(slider.getByTestId('playback-status')).toBeVisible();
  // The top comparison card supports independently selected preloaded epochs.
  const a=comet.observations.find(o=>o.detector===5), b=comet.observations.at(-1);
  await page.getByRole('button',{name:`Set ${a.obs_id} SPHEREx-D5 as A for comparison`}).click();
  await page.getByRole('button',{name:`Set ${b.obs_id} SPHEREx-D5 as B for comparison`}).click();
  const comparison=page.getByRole('region',{name:'Image comparison'}).first();
  await comparison.getByRole('button',{name:'Find Changes',exact:true}).click();
  await expect(comparison).toContainText('581.80 arcseconds',{timeout:60000});
  await expect(comparison).toContainText('not measured motion');
  await expect(comparison.getByRole('button',{name:'Difference',exact:true})).toBeDisabled();
  await comparison.getByLabel('Comparison comet view').selectOption('comet_centered');
  await comparison.getByRole('button',{name:'Find Changes',exact:true}).click();
  await expect(comparison).toContainText('PREDICTION-CENTERED VIEWS ONLY',{timeout:60000});
  await expect(comparison.locator('svg[aria-label="Predicted comet position"]')).toHaveCount(2);
  await comparison.screenshot({path:'test-results/comet-centered-comparison.png'});
  await slider.screenshot({path:'test-results/comet-tracking-playback.png'});
  expect(forbidden).toEqual([]);
});
