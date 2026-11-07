import { test, expect } from '@playwright/test';

const row = (n, band, lo, hi) => ({obs_id:`SYNTHETIC-FILTER-${n}`,energy_bandpassname:band,obs_collection:'test-only',
  observed_at_utc:`2026-06-2${n}T03:19:00.000`,s_ra:210,s_dec:54,t_exptime:100,em_min:lo*1e-6,em_max:hi*1e-6,
  access_url:`https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=synthetic-filter-${n}`,access_format:'x'});
const all = [row(1,'SPHEREx-D1',.75,1.1), row(2,'SPHEREx-D4',2.4,3.8), row(3,'SPHEREx-D4',2.4,3.8)];

test('wavelength filter is sent to the archive and only matching observations load', async ({page}) => {
  const queries = [];
  await page.route('**/api/images', route => route.fulfill({status:503, json:{code:'image_unavailable', message:'not needed'}}));
  await page.route('**/api/observations?**', route => {
    const params = new URL(route.request().url()).searchParams;
    queries.push(Object.fromEntries(params));
    const band = params.get('band'), um = params.get('wavelength_um');
    const rows = all.filter(r => (!band || r.energy_bandpassname === band) && (!um || (r.em_min <= um*1e-6 && r.em_max >= um*1e-6)));
    return route.fulfill({json:{status:'live',ra:210,dec:54,band,wavelength_um:um == null ? null : Number(um),count:rows.length,truncated:false,observations:rows}});
  });
  await page.goto('/', {waitUntil:'domcontentloaded'});
  const search = page.getByRole('button', {name:'Search SPHEREx Observations'});
  await search.click();
  await expect(page.getByRole('button', {name:'View Image'})).toHaveCount(3);
  await expect(page.getByTestId('active-filter')).toHaveText('Showing all wavelengths');
  expect(queries[0].band).toBeUndefined();

  // Picking a detector re-runs the search at once with only that band.
  await page.getByLabel(/^Wavelength/).selectOption('SPHEREx-D4');
  await expect(page.getByRole('button', {name:'View Image'})).toHaveCount(2);
  expect(queries.at(-1).band).toBe('SPHEREx-D4');
  await expect(page.getByTestId('active-filter')).toContainText('SPHEREx-D4 only');
  await expect(page.getByTestId('time-slider-id')).toContainText('SYNTHETIC-FILTER-2');

  // A specific wavelength: empty and out-of-range values are refused without querying.
  await page.getByLabel(/^Wavelength/).selectOption('custom');
  const count = queries.length;
  await search.click();
  await expect(page.locator('.wavelength-filter').getByRole('alert')).toContainText('Enter a wavelength');
  await page.getByLabel(/Wavelength in µm/).fill('9');
  await expect(page.locator('.wavelength-filter').getByRole('alert')).toContainText('from 0.7 to 5.1');
  expect(queries.length).toBe(count);
  await page.getByLabel(/Wavelength in µm/).fill('0.9');
  await expect(page.getByText('Covered by D1')).toBeVisible();
  await page.getByLabel(/Wavelength in µm/).press('Enter');
  await expect(page.getByRole('button', {name:'View Image'})).toHaveCount(1);
  expect(queries.at(-1).wavelength_um).toBe('0.9');
  await expect(page.getByTestId('active-filter')).toHaveText('Showing images covering 0.9 µm');
  await expect(page.locator('.observations')).toContainText('wavelength at your exact target may differ');
});
