import { test, expect } from '@playwright/test';

// Synthetic rows with image centres at increasing distance from the target.
const row = (n, offset) => ({obs_id:`SYNTHETIC-OFFSET-${n}`,energy_bandpassname:'SPHEREx-D2',obs_collection:'test-only',
  observed_at_utc:`2026-06-2${n}T03:19:00.000`,s_ra:210,s_dec:54 + offset,center_offset_deg:offset,t_exptime:100,em_min:1.1e-6,em_max:1.6e-6,
  access_url:`https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=synthetic-offset-${n}`,access_format:'x'});
const all = [row(1, .1), row(2, .4), row(3, .9), row(4, 2.2)];

test('image centre limit is sent to the archive, defaults to 0.5° and narrows the results', async ({page}) => {
  const queries = [];
  await page.route('**/api/images', route => route.fulfill({status:503, json:{code:'image_unavailable', message:'not needed'}}));
  await page.route('**/api/observations?**', route => {
    const params = new URL(route.request().url()).searchParams;
    queries.push(Object.fromEntries(params));
    const limit = params.get('max_offset_deg');
    const rows = all.filter(r => limit == null || r.center_offset_deg <= Number(limit));
    return route.fulfill({json:{status:'live',ra:210,dec:54,band:null,wavelength_um:null,max_offset_deg:limit == null ? null : Number(limit),
      count:rows.length,truncated:false,observations:rows}});
  });
  await page.goto('/', {waitUntil:'domcontentloaded'});
  await expect(page.getByLabel(/^Image centre/)).toHaveValue('0.5');
  await page.getByRole('button', {name:'Search SPHEREx Observations'}).click();
  await expect(page.getByRole('button', {name:'View Image'})).toHaveCount(2);
  expect(queries[0].max_offset_deg).toBe('0.5');
  await expect(page.getByTestId('active-offset')).toHaveText('image centres within 0.5° of the target');
  await expect(page.locator('.observations tbody tr').first()).toContainText('0.100');

  // Changing the limit re-runs the search straight away.
  await page.getByLabel(/^Image centre/).selectOption('0.25');
  await expect(page.getByRole('button', {name:'View Image'})).toHaveCount(1);
  expect(queries.at(-1).max_offset_deg).toBe('0.25');

  // "Anywhere" restores the old behaviour: no limit is sent.
  await page.getByLabel(/^Image centre/).selectOption('');
  await expect(page.getByRole('button', {name:'View Image'})).toHaveCount(4);
  expect(queries.at(-1).max_offset_deg).toBeUndefined();
  await expect(page.getByTestId('active-offset')).toHaveText('image centres at any distance');
});
