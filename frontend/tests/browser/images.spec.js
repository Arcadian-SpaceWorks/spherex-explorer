import { test, expect } from '@playwright/test';
import fs from 'node:fs';
const fixture = JSON.parse(fs.readFileSync(new URL('../fixtures/image.json',import.meta.url)));
const png = fs.readFileSync(new URL('../fixtures/synthetic.png',import.meta.url));
const fits = fs.readFileSync(new URL('../fixtures/synthetic.fits',import.meta.url));
const rows = [1,2].map(n => ({obs_id:`SYNTHETIC-BROWSER-FIXTURE-${n}`,energy_bandpassname:'SPHEREx-D2',obs_collection:'test-only',
  observed_at_utc:'2026-06-24T03:19:00.048',s_ra:210,s_dec:54,t_exptime:100,em_min:1e-6,em_max:4e-6,
  access_url:`https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=synthetic-browser-fixture-${n}`,access_format:'application/x-votable+xml;content=datalink'}));
async function setup(page) {
  await page.route('**/api/observations?**',route => route.fulfill({json:{status:'live',ra:210,dec:54,count:2,truncated:false,observations:rows}}));
  await page.route('**/api/images/*/preview',route => route.fulfill({contentType:'image/png',body:png}));
  await page.context().route('**/api/images/*/original',route => route.fulfill({contentType:'application/fits',headers:{'Content-Disposition':'attachment; filename="synthetic.fits"'},body:fits}));
  await page.route('**/api/images/*/pixel?**',route => {
    const params=new URL(route.request().url()).searchParams;
    return route.fulfill({json:{x:Number(params.get('x')),y:Number(params.get('y')),value:22,flags:0,masked:false,ra:210,dec:54,
      spectral:{wavelength_um:2.5,bandwidth_um:.25,approximate:true}}});
  });
  await page.goto('/',{waitUntil:'domcontentloaded'});
  await page.getByRole('button',{name:'Search SPHEREx Observations'}).click();
  await expect(page.getByRole('button',{name:'View Image'})).toHaveCount(2);
}

test('select observation, inspect science image, pan/zoom, read pixel and download original',async ({page}) => {
  let posted;
  await page.route('**/api/images',route => {if (route.request().headers()['x-skytracker-client'] !== 'time-slider') posted=route.request().postDataJSON();return route.fulfill({json:fixture});});
  await setup(page);
  await page.getByRole('button',{name:'View Image'}).first().click();
  await expect(page.getByTestId('fits-target')).toBeVisible();
  expect(posted.access_url).toBe(rows[0].access_url);
  await expect(page.locator('tr.observation-selected')).toContainText(rows[0].obs_id);
  const inspector=page.getByRole('region',{name:'FITS image inspector'});
  await expect(inspector).toContainText('without recentering on your selected target');
  await expect(inspector).toContainText('Wavelength varies across this image');
  await page.getByRole('button',{name:'Zoom in image'}).click();
  await expect(page.getByTestId('image-zoom')).toHaveText('140%');
  await page.getByRole('button',{name:'Pan image right'}).click();
  await expect(page.getByTestId('fits-canvas').locator('g').first()).not.toHaveAttribute('transform',/^translate\(0 0\)/);
  await page.getByRole('button',{name:'Fit image'}).click();
  await expect(page.getByTestId('image-zoom')).toHaveText('100%');
  await page.getByTestId('fits-canvas').click();
  await expect(page.locator('.pixel-readout')).toContainText('2.50000 µm');
  const downloadPromise=page.waitForEvent('download');
  await page.getByRole('link',{name:/Download original FITS/}).click();
  expect((await downloadPromise).suggestedFilename()).toBe('synthetic.fits');
  await page.screenshot({path:'test-results/image-inspector-fixture.png',fullPage:true});
});

test('loading and size-limit errors are explicit, retry works, selection clears with target',async ({page}) => {
  let incoming;
  const received=new Promise(resolve => {incoming=resolve;});
  await page.route('**/api/images',route => {if (route.request().headers()['x-skytracker-client'] === 'time-slider') return route.fulfill({json:fixture});incoming(route);});
  await setup(page);
  await page.getByRole('button',{name:'View Image'}).first().click();
  const route=await received;
  await expect(page.locator('.image-inspector [role=status]')).toContainText('Downloading and inspecting');
  await route.fulfill({status:413,json:{status:'unavailable',code:'file_too_large',message:'This FITS product exceeds the configured maximum download size.'}});
  await expect(page.getByRole('alert')).toContainText('maximum download size');
  await page.unroute('**/api/images');
  await page.route('**/api/images',route => route.fulfill({json:fixture}));
  await page.getByRole('button',{name:'Retry image'}).click();
  await expect(page.getByTestId('fits-target')).toBeVisible();
  await page.locator('#ra').fill('10');await page.locator('#dec').fill('20');
  await page.getByRole('button',{name:'Go To Coordinates'}).click();
  await expect(page.getByTestId('fits-canvas')).toHaveCount(0);
  await expect(page.getByText('Choose View Image on an observation')).toBeVisible();
});

test('row keyboard selection and mobile inspector fit the viewport',async ({page}) => {
  await page.setViewportSize({width:390,height:844});
  await page.route('**/api/images',route => route.fulfill({json:fixture}));
  await setup(page);
  const row=page.locator('.observations tbody tr').last();
  await row.focus();await page.keyboard.press('Enter');
  await expect(page.getByTestId('fits-target')).toBeVisible();
  await expect(row).toHaveAttribute('aria-selected','true');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
