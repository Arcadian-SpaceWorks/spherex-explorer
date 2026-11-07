import { test, expect } from '@playwright/test';

test('live original FITS renders with per-pixel WCS through the inspector', async ({page}) => {
  test.skip(process.env.SKYTRACKER_LIVE_FITS !== '1', 'Opt-in: may download a full ~70 MB IRSA product.');
  test.setTimeout(780000);
  await page.goto('/',{waitUntil:'domcontentloaded'});
  await page.getByRole('button',{name:'Search SPHEREx Observations'}).click();
  await expect(page.getByRole('button',{name:'View Image'}).first()).toBeVisible({timeout:70000});
  const prepared = page.waitForResponse(response => new URL(response.url()).pathname === '/api/images', {timeout:720000});
  await page.getByRole('button',{name:'View Image'}).first().click();
  const response=await prepared;
  expect(response.status()).toBe(200);
  const metadata=await response.json();
  expect(metadata.science_hdu).toBeGreaterThan(0);
  expect(metadata.width).toBe(2040);expect(metadata.height).toBe(2040);
  expect(metadata.spatial_wcs).toBe('available');expect(metadata.spectral_wcs).toBe('available');
  expect(metadata.sha256).toMatch(/^[a-f0-9]{64}$/);
  await expect(page.getByTestId('fits-target')).toBeVisible();
  const inspector=page.getByRole('region',{name:'FITS image inspector'});
  await expect(inspector).toContainText(metadata.observation_id);
  await page.getByTestId('fits-canvas').click();
  await expect(page.locator('.pixel-readout')).toContainText('µm', {timeout:15000});
  await expect(page.locator('.pixel-readout')).toContainText('ICRS');
  await inspector.screenshot({path:'test-results/live-fits-inspector.png'});
  console.log(`Live FITS: ${metadata.bytes} bytes; IMAGE HDU ${metadata.science_hdu}; cache_hit=${metadata.cache_hit}; center wavelength=${metadata.center.spectral.wavelength_um} µm`);
});
