import { test, expect } from '@playwright/test';
test('real Aladin initializes, clicks select ICRS coordinates, marker and navigation work', async ({page}) => {
  page.on('pageerror', error => console.log('Browser error:', error.message));
  page.on('requestfailed', req => console.log('Network failure:', req.url(), req.failure()?.errorText));
  const tile = page.waitForResponse(response => response.url().includes('stpubdata.s3.us-east-1.amazonaws.com/mast/skybackgrounds/DSSColor/Norder') && response.status() === 200, {timeout:30000});
  await page.goto('/', {waitUntil:'domcontentloaded'});
  await expect(page.getByTestId('fov')).toContainText('°', {timeout:60000});
  const host = page.getByTestId('sky-map');
  await expect(host.locator('canvas').first()).toBeVisible();
  const box = await host.boundingBox();
  const x = Math.round(box.width * .63), y = Math.round(box.height * .4);
  // Read the genuine API projection at the pixel being clicked as the oracle.
  const expected = await page.evaluate(({x,y}) => document.querySelector('[data-testid="sky-map"]').skyAtlas.pix2world(x,y,'icrs'), {x,y});
  await page.mouse.click(box.x+x, box.y+y);
  await expect.poll(async () => parseFloat(await page.getByTestId('selected-ra').textContent())).toBeCloseTo(expected[0], 1);
  await expect.poll(async () => parseFloat(await page.getByTestId('selected-dec').textContent())).toBeCloseTo(expected[1], 1);
  await page.locator('#ra').fill('83.822');
  await page.locator('#dec').fill('-5.391');
  await page.getByRole('button', {name:'Go To Coordinates'}).click();
  await expect(page.getByTestId('selected-ra')).toHaveText('83.822000°');
  const center = await page.evaluate(() => document.querySelector('[data-testid="sky-map"]').skyAtlas.getRaDec());
  expect(center[0]).toBeCloseTo(83.822,3); expect(center[1]).toBeCloseTo(-5.391,3);
  const marker = await page.evaluate(() => {
    const catalog = document.querySelector('[data-testid="sky-map"]').skyAtlas.view.catalogs.find(c => c.name === 'Selected location');
    return catalog.getSources().map(s => ({ra:s.ra,dec:s.dec}));
  });
  expect(marker).toEqual([{ra:83.822,dec:-5.391}]);
  const initialFov = await page.getByTestId('fov').textContent();
  await page.mouse.move(box.x + box.width/2, box.y + box.height/2);
  await page.mouse.wheel(0,-300);
  await expect(page.getByTestId('fov')).not.toHaveText(initialFov);
  await page.mouse.move(box.x + box.width/2, box.y + box.height/2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width/2 + 80, box.y + box.height/2 + 40, {steps:10});
  await page.mouse.up();
  await expect(page.getByTestId('selected-ra')).toHaveText('83.822000°');
  const moved = await page.evaluate(() => document.querySelector('[data-testid="sky-map"]').skyAtlas.getRaDec());
  expect(Math.abs(moved[0] - center[0])).toBeGreaterThan(.1);
  await tile;
  await page.screenshot({path:'test-results/dashboard.png',fullPage:true});
});
test('unavailable API is explicit and mobile layout fits', async ({page}) => {
  await page.route('**/api/observations?**', route => route.fulfill({status:503, contentType:'application/json', body:JSON.stringify({status:'unavailable', message:'IRSA unavailable', observations:[]})}));
  await page.setViewportSize({width:390,height:844});
  await page.goto('/', {waitUntil:'domcontentloaded'});
  await page.getByRole('button',{name:'Search SPHEREx Observations'}).click();
  await expect(page.getByRole('alert')).toContainText('IRSA unavailable');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test('search button returns live IRSA metadata through the Vite proxy', async ({page}) => {
  await page.goto('/', {waitUntil:'domcontentloaded'});
  const responsePromise = page.waitForResponse(response => response.url().includes('/api/observations?'));
  await page.getByRole('button',{name:'Search SPHEREx Observations'}).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const data = await response.json();
  expect(data.status).toBe('live');
  expect(data.count).toBeGreaterThan(0);
  await expect(page.getByText('Live data', {exact:true})).toBeVisible();
  await expect(page.locator('tbody tr')).toHaveCount(data.count);
  await expect(page.locator('tbody tr').first()).toContainText(data.observations[0].obs_id);
  await page.screenshot({path:'test-results/live-observations.png',fullPage:true});
});
