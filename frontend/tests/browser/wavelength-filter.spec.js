// Contributor filter interaction tests adapted to conservative product coverage.
import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import { wavelengthCoverage } from '../../src/wavelengths.js';
const fixture=JSON.parse(fs.readFileSync(new URL('../fixtures/image.json',import.meta.url)));
const rows=[
  {obs_id:'SYNTHETIC-D1',energy_bandpassname:'SPHEREx-D1',em_min:.75e-6,em_max:1.1e-6},
  {obs_id:'SYNTHETIC-D4',energy_bandpassname:'SPHEREx-D4',em_min:2.4e-6,em_max:3.8e-6},
  {obs_id:'SYNTHETIC-UNKNOWN',energy_bandpassname:'SPHEREx-D5',em_min:null,em_max:null},
].map((row,i)=>({...row,obs_collection:'test-only',observed_at_utc:`2026-06-2${i+1}T03:19:00.000`,s_ra:210,s_dec:54,t_exptime:100,
  access_url:`https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=fixture-${i}`}));

test('live detector and wavelength filters reach the API; unknown coverage is retained',async({page})=>{
  const queries=[];
  await page.route('**/api/images',route=>route.fulfill({json:fixture}));
  await page.route('**/api/images/*/preview',route=>route.fulfill({status:404,body:'fixture preview not used'}));
  await page.route('**/api/observations?**',route=>{
    const params=new URL(route.request().url()).searchParams;
    queries.push(Object.fromEntries(params));
    let observations=rows.filter(row=>!params.get('band')||row.energy_bandpassname===params.get('band'));
    const wave=params.get('wavelength_um');
    if(wave!=null)observations=observations.map(row=>({...row,wavelength_coverage:wavelengthCoverage(row,Number(wave))})).filter(row=>row.wavelength_coverage!=='range_excludes');
    return route.fulfill({json:{status:'live',ra:210,dec:54,band:params.get('band'),wavelength_um:wave==null?null:Number(wave),
      count:observations.length,truncated:false,unknown_wavelength_count:observations.filter(row=>row.wavelength_coverage==='unknown').length,observations}});
  });
  await page.goto('/');
  const search=page.getByRole('button',{name:'Search SPHEREx Observations'});
  await search.click();
  await expect(page.getByRole('button',{name:'View Image'})).toHaveCount(3);
  expect(queries[0]).not.toHaveProperty('max_offset_deg');
  await page.getByLabel('Wavelength / detector filter').selectOption('SPHEREx-D4');
  await expect(page.getByRole('button',{name:'View Image'})).toHaveCount(1);
  expect(queries.at(-1).band).toBe('SPHEREx-D4');
  await expect(page.getByTestId('active-filter')).toHaveText('Showing SPHEREx-D4 detector only');
  await expect(page.getByTestId('time-slider-id')).toContainText('SYNTHETIC-D4');
  await page.getByLabel('Wavelength / detector filter').selectOption('custom');
  const count=queries.length;
  await search.click();
  await expect(page.locator('.wavelength-filter').getByRole('alert')).toContainText('Enter a wavelength');
  expect(queries.length).toBe(count);
  await page.getByLabel(/Wavelength in µm/).fill('9');
  await search.click();
  expect(queries.length).toBe(count);
  await page.getByLabel(/Wavelength in µm/).fill('2.5');
  await page.getByLabel(/Wavelength in µm/).press('Enter');
  await expect(page.getByRole('button',{name:'View Image'})).toHaveCount(2);
  expect(queries.at(-1).wavelength_um).toBe('2.5');
  await expect(page.locator('.observations')).toContainText('1 unverified observations');
  await expect(page.locator('.observations')).toContainText('Unknown coverage; retained');
  await expect(page.locator('.observations')).toContainText('wavelength at your exact target may differ');
});

test('demo filtering uses real local detector identities and never drops unknown spectral bounds',async({page})=>{
  const archive=[];
  await page.route('**/*',route=>{
    const url=new URL(route.request().url());
    if(!['localhost','127.0.0.1'].includes(url.hostname))return route.abort();
    if(url.pathname==='/api/images'||url.pathname==='/api/observations'){archive.push(url.href);return route.abort();}
    return route.continue();
  });
  await page.goto('/?mode=demo');
  await expect(page.getByTestId('fits-target')).toBeVisible();
  await page.getByLabel('Wavelength / detector filter').selectOption('SPHEREx-D5');
  await expect(page.getByRole('button',{name:'View Image'})).toHaveCount(2);
  await expect(page.getByTestId('time-slider-time')).toHaveText('2026-05-22T19:40:19.088 UTC');
  await page.getByRole('button',{name:'Next observation'}).click();
  await expect(page.getByTestId('time-slider-time')).toHaveText('2026-05-22T19:42:28.021 UTC');
  await page.getByLabel('Wavelength / detector filter').selectOption('SPHEREx-D1');
  await expect(page.getByRole('button',{name:'View Image'})).toHaveCount(0);
  await expect(page.locator('.observations')).toContainText('No preloaded observations match this filter');
  await page.getByLabel('Wavelength / detector filter').selectOption('custom');
  await page.getByLabel(/Wavelength in µm/).fill('2.5');
  await page.getByRole('button',{name:'Apply preloaded filter'}).click();
  await expect(page.getByRole('button',{name:'View Image'})).toHaveCount(3);
  await expect(page.locator('.observations')).toContainText('3 unverified observations');
  expect(archive).toEqual([]);
});
