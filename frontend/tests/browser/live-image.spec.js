import { test, expect } from '@playwright/test';
import { chronologicalFrames } from '../../src/timeline.js';

test('live cutout FITS renders with per-pixel WCS through the inspector', async ({page}) => {
  test.skip(process.env.SKYTRACKER_LIVE_FITS !== '1', 'Opt-in: downloads a real IRSA cutout.');
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
  expect(metadata.cutout.size_deg).toBe(0.3);
  expect(metadata.width).toBeGreaterThan(0);expect(metadata.height).toBeGreaterThan(0);
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

test('live timeline switches real FITS images while the viewer shares preparation', async ({page}) => {
  test.skip(process.env.SKYTRACKER_LIVE_FITS !== '1', 'Opt-in: downloads two real IRSA FITS cutouts.');
  test.setTimeout(1500000);
  const busy = [];
  page.on('response', response => {
    if (response.url().includes('/api/images') && response.status() === 503) busy.push(response.url());
  });
  await page.goto('/', {waitUntil: 'domcontentloaded'});
  const observations = page.waitForResponse(response => response.url().includes('/api/observations?'));
  const initial = page.waitForResponse(response => new URL(response.url()).pathname === '/api/images'
    && response.request().headers()['x-skytracker-client'] === 'time-slider', {timeout: 720000});
  await page.getByRole('button', {name: 'Search SPHEREx Observations'}).click();
  const archiveResponse = await observations;
  expect(archiveResponse.status()).toBe(200);
  const data = await archiveResponse.json();
  const frames = chronologicalFrames(data.observations).frames;
  expect(frames.length).toBeGreaterThan(1);
  const explorer = page.getByRole('region', {name: 'Astronomical time explorer'});
  // Ask the inspector for the same resource while the slider prepares it.
  const viewerResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/images'
    && response.request().headers()['x-skytracker-client'] !== 'time-slider', {timeout: 720000});
  const rowIndex = data.observations.findIndex(row => row.access_url === frames[0].access_url);
  await page.getByRole('button', {name: 'View Image', exact: true}).nth(rowIndex).click();
  const firstResponse = await initial;
  const inspectorResponse = await viewerResponse;
  expect(firstResponse.status(), await firstResponse.text()).toBe(200);
  expect(inspectorResponse.status(), await inspectorResponse.text()).toBe(200);
  const first = await firstResponse.json();
  const inspector = await inspectorResponse.json();
  expect(first.access_url).toBe(frames[0].access_url);
  expect(inspector.image_id).toBe(first.image_id);
  expect(first.cache_hit || inspector.cache_hit).toBe(true);
  await expect(page.getByTestId('fits-canvas')).toBeVisible();
  async function verifyFrame(frame, metadata) {
    expect(metadata.observation_id).toBe(frame.obs_id);
    const utc = value => Date.parse(/[zZ]$/.test(value) ? value : `${value}Z`);
    expect(Number.isFinite(utc(metadata.observed_at_utc))).toBe(true);
    await expect(explorer.getByTestId('time-slider-time')).toHaveText(
      `${new Date(utc(frame.observed_at_utc)).toISOString().replace(/Z$/, '')} UTC`);
    if (metadata.observed_at_utc !== frame.observed_at_utc) {
      await expect(explorer).toContainText('FITS header time differs from the archive timestamp');
    }
    await expect(explorer.getByTestId('time-slider-id')).toHaveText(`Observation ${frame.obs_id}`);
    await expect(explorer.getByTestId('time-slider-image')).toHaveAttribute('src', metadata.preview_url);
    await expect.poll(() => explorer.getByTestId('time-slider-image').evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  }
  await verifyFrame(frames[0], first);
  const nextResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/images'
    && response.request().postDataJSON().access_url === frames[1].access_url, {timeout: 720000});
  await explorer.getByRole('button', {name: 'Next observation'}).click();
  await page.getByTestId('fits-canvas').click();
  const secondResponse = await nextResponse;
  expect(secondResponse.status(), await secondResponse.text()).toBe(200);
  const second = await secondResponse.json();
  expect(second.access_url).toBe(frames[1].access_url);
  expect(second.image_id).not.toBe(first.image_id);
  await verifyFrame(frames[1], second);
  await expect(page.locator('.pixel-readout')).toContainText('µm', {timeout: 720000});
  expect(busy).toEqual([]);
  console.log(JSON.stringify({liveFrames: [first, second].map(item => ({id: item.observation_id,
    time: item.observed_at_utc, detector: item.detector, bytes: item.bytes, cache_hit: item.cache_hit})), busy}));
});
