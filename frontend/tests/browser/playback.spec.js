import { test, expect } from '@playwright/test';
import fs from 'node:fs';

const manifest = JSON.parse(fs.readFileSync(new URL('../../public/demo/manifest.json', import.meta.url)));
const m31 = manifest.targets.find(item => item.id === 'm31');
const fixture = JSON.parse(fs.readFileSync(new URL('../fixtures/image.json', import.meta.url)));
const png = fs.readFileSync(new URL('../fixtures/synthetic.png', import.meta.url));

async function demoM31(page) {
  await page.route('**/*', route => ['127.0.0.1', 'localhost'].includes(new URL(route.request().url()).hostname) ? route.continue() : route.abort());
  await page.goto('/?mode=demo');
  await page.getByLabel('Preloaded target').selectOption('m31');
  const explorer = page.getByRole('region', {name: 'Astronomical time explorer'});
  await expect(explorer.getByTestId('time-slider-id')).toHaveText(`Observation ${m31.observations[0].obs_id}`);
  return explorer;
}

test('play steps through every observation in time order, then offers replay', async ({page}) => {
  const explorer = await demoM31(page);
  await explorer.getByRole('button', {name: 'Play observations in time order'}).click();
  await expect(explorer.getByTestId('playback-status')).toBeVisible();
  for (let step = 2; step <= m31.observations.length; step++) {
    await expect(explorer).toContainText(`Step ${step} of ${m31.observations.length}`, {timeout: 15000});
  }
  await expect(explorer.getByRole('button', {name: 'Replay observations from the start'})).toBeVisible({timeout: 10000});
  await expect(explorer.getByTestId('playback-status')).toHaveCount(0);
});

test('pause stops playback where it is', async ({page}) => {
  const explorer = await demoM31(page);
  await explorer.getByRole('button', {name: 'Play observations in time order'}).click();
  await expect(explorer).toContainText('Step 2 of', {timeout: 15000});
  await explorer.getByRole('button', {name: 'Pause playback'}).click();
  const text = await explorer.locator('.time-readout').innerText();
  await page.waitForTimeout(3500);  // More than two playback steps.
  expect(await explorer.locator('.time-readout').innerText()).toBe(text);
});

test('playback waits for a slow live image instead of skipping past it', async ({page}) => {
  // TEST DATA: two synthetic live rows; the second image takes 5 s to prepare.
  const rows = [1, 2].map(n => ({obs_id: `SYNTHETIC-PLAY-${n}`, energy_bandpassname: 'SPHEREx-D1', obs_collection: 'test-only',
    observed_at_utc: `2026-0${n}-01T00:00:00.000`, s_ra: 210, s_dec: 54, t_exptime: 1, em_min: null, em_max: null,
    access_format: 'x', access_url: `https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=synthetic-play-${n}`}));
  await page.route('**/api/observations?**', route => route.fulfill({json: {status: 'live', ra: 210, dec: 54, count: 2, truncated: false, observations: rows}}));
  await page.route('**/api/images/*/preview', route => route.fulfill({contentType: 'image/png', body: png}));
  await page.route('**/api/images', async route => {
    if (route.request().postDataJSON().access_url === rows[1].access_url) await new Promise(resolve => setTimeout(resolve, 5000));
    await route.fulfill({json: {...fixture, observation_id: route.request().postDataJSON().access_url.endsWith('2') ? rows[1].obs_id : rows[0].obs_id}}).catch(() => {});
  });
  await page.goto('/', {waitUntil: 'domcontentloaded'});
  await page.getByRole('button', {name: 'Search SPHEREx Observations'}).click();
  const explorer = page.getByRole('region', {name: 'Astronomical time explorer'});
  await expect(explorer.getByTestId('time-slider-image')).toBeVisible();
  await explorer.getByRole('button', {name: 'Play observations in time order'}).click();
  await expect(explorer).toContainText('Step 2 of 2', {timeout: 5000});
  await expect(explorer.getByTestId('playback-status')).toContainText('waiting for step 2 to load');
  await expect(explorer.getByTestId('time-slider-image')).toBeVisible({timeout: 10000});
  await expect(explorer.getByRole('button', {name: 'Replay observations from the start'})).toBeVisible({timeout: 5000});
});

test('export records a WebM time-lapse of the sequence', async ({page}) => {
  const explorer = await demoM31(page);
  const exporter = explorer.getByTestId('timelapse-export');
  await expect(exporter).toContainText('own brightness scale');
  const download = page.waitForEvent('download', {timeout: 60000});
  await exporter.getByRole('button', {name: 'Export time-lapse video'}).click();
  await expect(exporter.getByRole('status')).toContainText('Preparing frame');
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^spherex_timelapse_ra10\.685_dec41\.269_\d{4}-\d{2}-\d{2}\.webm$/);
  const bytes = fs.statSync(await file.path()).size;
  expect(bytes).toBeGreaterThan(10_000);
  await expect(exporter.getByTestId('timelapse-download')).toBeVisible();
  // The recorded file is a real WebM (EBML header).
  expect(fs.readFileSync(await file.path()).subarray(0, 4).toString('hex')).toBe('1a45dfa3');
});
