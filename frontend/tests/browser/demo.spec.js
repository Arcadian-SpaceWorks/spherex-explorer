import { test, expect } from '@playwright/test';
import fs from 'node:fs';
const manifest = JSON.parse(fs.readFileSync(new URL('../../public/demo/manifest.json', import.meta.url)));
const target = manifest.targets.find(item => item.status === 'ready');

async function blockArchive(page) {
  const external = [], live = [];
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) {external.push(url.href); return route.abort();}
    if (url.pathname === '/api/images' || url.pathname === '/api/observations') {live.push(url.href); return route.abort();}
    return route.continue();
  });
  return {external, live};
}
async function visiblePreview(page) {
  await expect.poll(() => page.getByTestId('time-slider-image').evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  await expect(page.getByTestId('fits-target')).toBeVisible();
}

test('real preloaded playback, local science pixel readout and target changes work with external network blocked', async ({page}) => {
  const traffic = await blockArchive(page);
  await page.goto('/?mode=demo');
  await expect(page.getByRole('radio', {name:/Demo Mode/})).toBeChecked();
  await visiblePreview(page);
  await expect(page.getByText('Preloaded data', {exact:true})).toBeVisible();
  await expect(page.getByTestId('sky-map')).toHaveCount(0);
  const explorer = page.getByRole('region', {name:'Astronomical time explorer'});
  await expect(explorer).toContainText('No source motion or brightness variation has been validated');
  await expect(explorer).toContainText('not spatially registered');
  await expect(explorer.getByRole('note')).not.toContainText('Synthetic fixture');
  await expect(explorer.getByTestId('time-slider-id')).toHaveText(`Observation ${target.observations[0].obs_id}`);
  const response = page.waitForResponse(r => r.url().includes('/api/demo/images/') && r.url().includes('/pixel?'));
  await page.getByTestId('fits-canvas').click();
  expect((await response).status()).toBe(200);
  await expect(page.locator('.pixel-readout')).toContainText('ICRS');
  await explorer.getByRole('button', {name:'Next observation'}).click();
  await expect(explorer.getByTestId('time-slider-image')).toHaveAttribute('src', target.observations[1].preview_path);
  await expect.poll(() => explorer.getByTestId('time-slider-image').evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  await page.getByLabel('Preloaded target').selectOption('m31');
  const m31 = manifest.targets.find(item => item.id === 'm31');
  await expect(explorer.getByTestId('time-slider-id')).toHaveText(`Observation ${m31.observations[0].obs_id}`);
  await expect(explorer).toContainText(`Step 1 of ${m31.observations.length}`);
  await expect.poll(() => explorer.getByTestId('time-slider-image').evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  await expect(page.getByTestId('fits-target')).toBeVisible();
  await page.getByLabel('Preloaded target').selectOption('m101');
  await visiblePreview(page);
  expect(traffic).toEqual({external:[], live:[]});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({path:'test-results/preloaded-demo-mobile.png', fullPage:true});
});

test('switching to Live Mode clears preloaded data and uses the existing API', async ({page}) => {
  await blockArchive(page);
  await page.goto('/?mode=demo');
  await visiblePreview(page);
  await page.getByRole('radio', {name:/Live Mode/}).check();
  await expect(page.getByTestId('fits-canvas')).toHaveCount(0);
  await expect(page.getByTestId('time-slider-image')).toHaveCount(0);
  await expect(page.getByTestId('sky-map')).toBeVisible();
  await page.route('**/api/observations?**', route => route.fulfill({json:{status:'live',ra:210,dec:54,count:0,observations:[]}}));
  await page.getByRole('button', {name:'Search SPHEREx Observations'}).click();
  await expect(page.getByText('Live data', {exact:true})).toBeVisible();
  await page.getByRole('radio', {name:/Demo Mode/}).check();
  await visiblePreview(page);
});

test('missing or invalid manifest is explicit and never falls back to live archive', async ({page}) => {
  const traffic = await blockArchive(page);
  await page.route('**/demo/manifest.json', route => route.fulfill({status:404,body:'Missing'}));
  await page.goto('/?mode=demo');
  await expect(page.locator('.observations').getByRole('alert')).toContainText('manifest missing');
  await expect(page.getByTestId('fits-canvas')).toHaveCount(0);
  await page.route('**/demo/manifest.json', route => route.fulfill({json:{...manifest,schema_version:999}}));
  await page.reload();
  await expect(page.locator('.observations').getByRole('alert')).toContainText('Invalid demo manifest');
  expect(traffic.live).toEqual([]);
});

test('missing previews recover through existing viewer and slider retry controls', async ({page}) => {
  await blockArchive(page);
  await page.route('**/demo/assets/*/preview.png', route => route.fulfill({status:404,body:'Missing'}));
  await page.goto('/?mode=demo');
  const explorer = page.getByRole('region', {name:'Astronomical time explorer'});
  await expect(explorer.getByRole('alert')).toContainText('preview image failed to load');
  await expect(page.locator('.image-inspector').getByRole('alert')).toContainText('Preview unavailable');
  await page.unroute('**/demo/assets/*/preview.png');
  await explorer.getByRole('button', {name:'Retry this observation image'}).click();
  await page.getByRole('button', {name:'Reload image', exact:true}).click();
  await visiblePreview(page);
});

test('a target without prepared cutouts is explicitly unavailable', async ({page}) => {
  // TEST DATA: the real manifest plus one synthetic unprepared target, served only in this test.
  const missing = {id: 'test-missing', name: 'Unprepared test target', ra: 1, dec: 2,
    coordinate_source: 'https://example.org/test-only', status: 'missing',
    missing_reason: 'No verified local cutouts have been supplied for this target.', observations: []};
  await blockArchive(page);
  // Registered after blockArchive's catch-all route, so this one takes priority.
  await page.route('**/demo/manifest.json', route => route.fulfill({json: {...manifest, targets: [...manifest.targets, missing]}}));
  await page.goto('/?mode=demo');
  await visiblePreview(page);
  await page.getByLabel('Preloaded target').selectOption('test-missing');
  await expect(page.getByText(missing.missing_reason)).toBeVisible();
  await expect(page.getByTestId('time-slider')).toHaveCount(0);
  await expect(page.getByTestId('fits-canvas')).toHaveCount(0);
});

test('demo rows show the exact wavelength at the target, read from the local images', async ({page}) => {
  const traffic = await blockArchive(page);
  await page.goto('/?mode=demo');
  await visiblePreview(page);
  await page.getByLabel('Preloaded target').selectOption('m31');
  const m31 = manifest.targets.find(item => item.id === 'm31');
  const values = page.locator('.observations').getByTestId('target-wavelength');
  await expect(values).toHaveCount(m31.observations.length);
  for (const observation of m31.observations) {
    const metadata = JSON.parse(fs.readFileSync(new URL(`../../public${observation.metadata_path}`, import.meta.url)));
    const row = page.locator('.observations tr', {hasText: observation.obs_id}).filter({hasText: `SPHEREx-D${observation.detector}`});
    await expect(row.getByTestId('target-wavelength')).toHaveText(metadata.target.spectral.wavelength_um.toFixed(4));
  }
  await expect(page.getByRole('button', {name: /^Measure wavelength/})).toHaveCount(0);  // Never downloads in Demo Mode.
  expect(traffic).toEqual({external: [], live: []});
});
