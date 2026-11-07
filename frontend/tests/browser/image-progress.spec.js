// Contributor elapsed/cancel/retry interaction adapted to the actual API contract.
import {test,expect} from '@playwright/test';
import fs from 'node:fs';
const fixture=JSON.parse(fs.readFileSync(new URL('../fixtures/image.json',import.meta.url)));
const png=fs.readFileSync(new URL('../fixtures/synthetic.png',import.meta.url));
const rows=[1,2].map(n=>({obs_id:`SYNTHETIC-PROGRESS-${n}`,obs_collection:'test-only',energy_bandpassname:'SPHEREx-D2',
  observed_at_utc:`2026-06-2${n}T03:19:00.000`,access_url:`https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=progress-fixture-${n}`}));

test('progress reports elapsed wait without invented stages; stop/retry ignores stale requests',async({page})=>{
  let requested;
  const incoming=new Promise(resolve=>{requested=resolve;});
  await page.route('**/api/observations?**',route=>route.fulfill({json:{status:'live',ra:210,dec:54,count:2,observations:rows}}));
  await page.route('**/api/images/*/preview',route=>route.fulfill({contentType:'image/png',body:png}));
  await page.route('**/api/images',route=>{
    if(route.request().headers()['x-skytracker-client']==='time-slider')return route.fulfill({json:fixture});
    requested(route);
  });
  await page.goto('/');
  await page.getByRole('button',{name:'Search SPHEREx Observations'}).click();
  await page.getByRole('button',{name:'View Image'}).first().click();
  const held=await incoming;
  const inspector=page.getByRole('region',{name:'FITS image inspector'});
  await expect(inspector.getByTestId('download-progress')).toContainText('Downloading and inspecting');
  await expect(inspector.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow');
  await expect(inspector.getByTestId('download-elapsed')).toContainText('0:01');
  await expect(inspector.getByTestId('download-progress')).toContainText('Byte progress and completion time are unavailable');
  await inspector.getByRole('button',{name:'Stop waiting',exact:true}).click();
  await expect(inspector).toContainText('Stopped waiting for this image');
  await expect(inspector.getByRole('progressbar')).toHaveCount(0);
  // A response from the stopped request must not replace the next selection.
  await held.fulfill({json:{...fixture,observation_id:'SYNTHETIC-STALE-RESPONSE'}});
  await page.unroute('**/api/images');
  await page.route('**/api/images',route=>route.fulfill({json:fixture}));
  await inspector.getByRole('button',{name:'Load image again'}).click();
  await expect(page.getByTestId('fits-target')).toBeVisible();
  await expect(inspector).not.toContainText('SYNTHETIC-STALE-RESPONSE');
  await expect(inspector.getByRole('progressbar')).toHaveCount(0);
  await page.getByRole('combobox',{name:'Data mode',exact:true}).selectOption('demo');
  await expect(page.getByTestId('fits-target')).toBeVisible();
  await expect(inspector).toContainText('Preloaded real SPHEREx cutout');
});
