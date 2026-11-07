import { test, expect } from '@playwright/test';
import fs from 'node:fs';

const fixture = JSON.parse(fs.readFileSync(new URL('../fixtures/image.json', import.meta.url)));
const png = {
  'synthetic-time-early': Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64'),
  'synthetic-time-mid': Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64'),
  'synthetic-time-late': Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPj/HwADBwIAMCbHYQAAAABJRU5ErkJggg==', 'base64'),
};
const times = {
  'synthetic-time-early': '2025-01-03T04:00:00.000',
  'synthetic-time-mid': '2025-03-18T21:15:30.000',
  'synthetic-time-late': '2025-11-02T11:42:10.500',
};
function row(id, extra = {}) {
  return {obs_id: `SYNTHETIC-TIME-${id.split('-').pop().toUpperCase()}`, energy_bandpassname: extra.energy_bandpassname || 'SPHEREx-D1',
    obs_collection: 'test-only', observed_at_utc: times[id], s_ra: 210, s_dec: 54, t_exptime: 120,
    em_min: extra.em_min ?? 1.1e-6, em_max: extra.em_max ?? 1.6e-6,
    access_url: `https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=${id}`,
    access_format: 'application/x-votable+xml;content=datalink', ...extra};
}
const sequence = [
  row('synthetic-time-mid', {energy_bandpassname: 'SPHEREx-D2', em_min: 2.1e-6, em_max: 3.2e-6, obs_id: 'SYNTHETIC-TIME-MID'}),
  row('synthetic-time-late', {energy_bandpassname: 'SPHEREx-D3', em_min: 3.4e-6, em_max: 4.8e-6, obs_id: 'SYNTHETIC-TIME-LATE'}),
  row('synthetic-time-early', {obs_id: 'SYNTHETIC-TIME-EARLY'}),
  {obs_id: 'SYNTHETIC-TIME-NOLINK', energy_bandpassname: 'SPHEREx-D1', obs_collection: 'test-only', observed_at_utc: '2025-02-01T00:00:00.000', s_ra: 210, s_dec: 54, t_exptime: 10, em_min: 1e-6, em_max: 2e-6, access_url: null, access_format: null},
];

function payload(id) {
  return {...fixture, observation_id: `SYNTHETIC-TIME-${id.split('-').pop().toUpperCase()}`, observed_at_utc: times[id],
    preview_url: `/api/images/${id}/preview`, image_id: id, detector: id.endsWith('late') ? 3 : id.endsWith('mid') ? 2 : 1};
}

async function search(page, observations, {failEarly = false} = {}) {
  await page.route('**/api/observations?**', route => route.fulfill({json: {status: 'live', ra: 210, dec: 54, count: observations.length, truncated: false, observations}}));
  await page.route('**/api/images/*/preview', route => {
    const id = new URL(route.request().url()).pathname.split('/').at(-2);
    return route.fulfill({contentType: 'image/png', body: png[id] || png['synthetic-time-early']});
  });
  await page.route('**/api/images', route => {
    if (route.request().method() !== 'POST') return route.fallback();
    const id = new URL(route.request().postDataJSON().access_url).searchParams.get('ID');
    if (failEarly && id === 'synthetic-time-early') return route.fulfill({status: 503, json: {message: 'Synthetic preview failed for this fixture.'}});
    return route.fulfill({json: payload(id)});
  });
  await page.goto('/', {waitUntil: 'domcontentloaded'});
  await page.getByRole('button', {name: 'Search SPHEREx Observations'}).click();
}

async function displayedPixel(explorer) {
  const image = explorer.getByTestId('time-slider-image');
  await expect.poll(() => image.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  return image.evaluate(img => {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 1;
    const context = canvas.getContext('2d');
    context.drawImage(img, 0, 0);
    return [...context.getImageData(0, 0, 1, 1).data];
  });
}

test('slider follows chronological observations, not arrival order or equal time gaps', async ({page}) => {
  await search(page, sequence);
  const explorer = page.getByRole('region', {name: 'Astronomical time explorer'});
  await expect(explorer.getByTestId('time-slider-id')).toHaveText('Observation SYNTHETIC-TIME-EARLY');
  await expect(explorer.getByTestId('time-slider-time')).toHaveText('2025-01-03T04:00:00.000 UTC');
  await expect(explorer.getByTestId('time-slider')).toHaveValue('0');
  await expect(explorer.getByTestId('time-slider-image')).toHaveAttribute('src', /synthetic-time-early\/preview$/);
  const earlyPixel = await displayedPixel(explorer);
  await expect(explorer.getByRole('note')).toContainText('not a live NASA observation');
  await expect(explorer).toContainText('not spatially registered');
  await expect(explorer).toContainText('SPHEREx-D1, SPHEREx-D2, SPHEREx-D3');
  await expect(explorer).toContainText('no usable image link');
  await expect(page.getByRole('region', {name: 'FITS image inspector'})).toContainText('Choose View Image');

  await explorer.getByTestId('time-slider').fill('1');
  await expect(explorer.getByTestId('time-slider-id')).toHaveText('Observation SYNTHETIC-TIME-MID');
  await expect(explorer.getByTestId('time-slider-time')).toHaveText('2025-03-18T21:15:30.000 UTC');
  await expect(explorer.getByTestId('time-slider-image')).toHaveAttribute('src', /synthetic-time-mid\/preview$/);
  const middlePixel = await displayedPixel(explorer);
  expect(middlePixel).not.toEqual(earlyPixel);
  await expect(explorer).toContainText('2.100 – 3.200 µm');

  await explorer.getByRole('button', {name: 'Next observation'}).click();
  await expect(explorer.getByTestId('time-slider-id')).toHaveText('Observation SYNTHETIC-TIME-LATE');
  await expect(explorer.getByTestId('time-slider')).toHaveValue('2');
  await expect(explorer.getByTestId('time-slider-image')).toHaveAttribute('src', /synthetic-time-late\/preview$/);
  const lastPixel = await displayedPixel(explorer);
  expect(lastPixel).not.toEqual(earlyPixel);
  expect(lastPixel).not.toEqual(middlePixel);
  await explorer.getByTestId('time-slider').focus();
  await page.keyboard.press('ArrowLeft');
  await expect(explorer.getByTestId('time-slider-id')).toHaveText('Observation SYNTHETIC-TIME-MID');
  await page.keyboard.press('Home');
  await expect(explorer.getByTestId('time-slider-time')).toHaveText('2025-01-03T04:00:00.000 UTC');

  await page.locator('#ra').fill('10');
  await page.locator('#dec').fill('20');
  await page.getByRole('button', {name: 'Go To Coordinates'}).click();
  await expect(explorer.getByTestId('time-slider')).toHaveCount(0);
  await expect(explorer.getByTestId('time-slider-image')).toHaveCount(0);
  await expect(explorer).not.toContainText('SYNTHETIC-TIME-EARLY');
  await expect(explorer).toContainText('Search SPHEREx observations');
  await expect(page.getByTestId('fits-canvas')).toHaveCount(0);
});

test('broken preview recovers on retry and malformed time is explicitly unavailable', async ({page}) => {
  await search(page, [row('synthetic-time-early', {observed_at_utc: 'invalid'})]);
  const explorer = page.getByRole('region', {name: 'Astronomical time explorer'});
  await expect(explorer.getByTestId('time-slider-time')).toHaveText('Time unavailable');
  await expect(explorer).toContainText('placed after the dated frames');
  await displayedPixel(explorer);
  await page.route('**/api/images', route => route.fulfill({json: {
    ...payload('synthetic-time-early'), preview_url: '/api/images/synthetic-time-broken/preview',
  }}));
  await page.route('**/api/images/*/preview', route => route.fulfill({status: 404, body: 'Missing preview'}));
  await page.getByRole('button', {name: 'Search SPHEREx Observations'}).click();
  await expect(explorer.getByRole('alert')).toContainText('preview image failed to load');
  await page.unroute('**/api/images/*/preview');
  await page.route('**/api/images/*/preview', route => route.fulfill({contentType: 'image/png', body: png['synthetic-time-early']}));
  await explorer.getByRole('button', {name: 'Retry this observation image'}).click();
  await displayedPixel(explorer);
  await expect(explorer.getByRole('alert')).toHaveCount(0);
});

test('a delayed image from the previous step cannot replace the selected image', async ({page}) => {
  let release;
  const held = new Promise(resolve => {release = resolve;});
  let arrived;
  const incoming = new Promise(resolve => {arrived = resolve;});
  let finished;
  const completed = new Promise(resolve => {finished = resolve;});
  await search(page, sequence);
  const explorer = page.getByRole('region', {name: 'Astronomical time explorer'});
  await displayedPixel(explorer);
  await page.route('**/api/images', async route => {
    const id = new URL(route.request().postDataJSON().access_url).searchParams.get('ID');
    if (id === 'synthetic-time-mid') {arrived(); await held;}
    await route.fulfill({json: payload(id)});
    if (id === 'synthetic-time-mid') finished();
  });
  await explorer.getByRole('button', {name: 'Next observation'}).click();
  await incoming;
  await expect(explorer.getByRole('status')).toContainText('Loading');
  await explorer.getByRole('button', {name: 'Next observation'}).click();
  await displayedPixel(explorer);
  release();
  await completed;
  await expect(explorer.getByTestId('time-slider-id')).toContainText('LATE');
  await expect(explorer.getByTestId('time-slider-image')).toHaveAttribute('src', /synthetic-time-late\/preview$/);
});

test('new coordinates and search supersede a delayed observation search', async ({page}) => {
  await search(page, sequence);
  const explorer = page.getByRole('region', {name: 'Astronomical time explorer'});
  await displayedPixel(explorer);
  let release;
  const held = new Promise(resolve => {release = resolve;});
  let arrived;
  const incoming = new Promise(resolve => {arrived = resolve;});
  let finished;
  const completed = new Promise(resolve => {finished = resolve;});
  await page.route('**/api/observations?**', async route => {
    const ra = Number(new URL(route.request().url()).searchParams.get('ra'));
    if (ra !== 10) {arrived(); await held;}
    const observations = ra === 10 ? [row('synthetic-time-late')] : sequence;
    await route.fulfill({json: {status: 'live', ra, dec: 20, count: observations.length, observations}});
    if (ra !== 10) finished();
  });
  await page.getByRole('button', {name: 'Search SPHEREx Observations'}).click();
  await incoming;
  await expect(explorer.getByTestId('time-slider')).toHaveCount(0);
  await page.locator('#ra').fill('10');
  await page.locator('#dec').fill('20');
  await page.getByRole('button', {name: 'Go To Coordinates'}).click();
  await page.getByRole('button', {name: 'Search SPHEREx Observations'}).click();
  await expect(explorer.getByTestId('time-slider-id')).toContainText('LATE');
  release();
  await completed;
  await displayedPixel(explorer);
  await expect(explorer.getByTestId('time-slider')).toBeDisabled();
  await expect(explorer.getByTestId('time-slider-id')).toContainText('LATE');
});

test('a failed frame stays on the slider and the next observation still loads', async ({page}) => {
  await search(page, sequence.filter(item => item.access_url), {failEarly: true});
  const explorer = page.getByRole('region', {name: 'Astronomical time explorer'});
  await expect(explorer.getByRole('alert')).toContainText('Synthetic preview failed');
  await expect(explorer.getByTestId('time-slider-image')).toHaveCount(0);
  await explorer.getByRole('button', {name: 'Next observation'}).click();
  await expect(explorer.getByTestId('time-slider-image')).toHaveAttribute('src', /synthetic-time-mid\/preview$/);
  await expect(explorer.getByRole('alert')).toHaveCount(0);
});

test('FITS viewer remains usable while a slider image is loading and coordinates invalidate it', async ({page}) => {
  await search(page, sequence);
  const explorer = page.getByRole('region', {name: 'Astronomical time explorer'});
  await displayedPixel(explorer);
  let release;
  const held = new Promise(resolve => {release = resolve;});
  let arrived;
  const incoming = new Promise(resolve => {arrived = resolve;});
  let finished;
  const completed = new Promise(resolve => {finished = resolve;});
  await page.route('**/api/images', async route => {
    const id = new URL(route.request().postDataJSON().access_url).searchParams.get('ID');
    const slider = route.request().headers()['x-skytracker-client'] === 'time-slider';
    if (slider && id === 'synthetic-time-mid') {arrived(); await held;}
    await route.fulfill({json: payload(id)});
    if (slider && id === 'synthetic-time-mid') finished();
  });
  await explorer.getByRole('button', {name: 'Next observation'}).click();
  await incoming;
  await page.getByRole('button', {name: 'View Image', exact: true}).nth(1).click();
  await expect(page.getByTestId('fits-canvas')).toBeVisible();
  await page.locator('#ra').fill('10');
  await page.locator('#dec').fill('20');
  await page.getByRole('button', {name: 'Go To Coordinates'}).click();
  release();
  await completed;
  await expect(explorer.getByTestId('time-slider-image')).toHaveCount(0);
  await expect(explorer.getByTestId('time-slider')).toHaveCount(0);
  await expect(page.getByTestId('fits-canvas')).toHaveCount(0);
});

test('zero observations and a single observation have explicit slider states', async ({page}) => {
  await search(page, []);
  const explorer = page.getByRole('region', {name: 'Astronomical time explorer'});
  await expect(explorer).toContainText('No observations were returned');
  await expect(explorer.getByTestId('time-slider')).toHaveCount(0);

  await page.unroute('**/api/observations?**');
  await page.route('**/api/observations?**', route => route.fulfill({json: {status: 'live', ra: 210, dec: 54, count: 1, truncated: false, observations: [row('synthetic-time-early', {obs_id: 'SYNTHETIC-TIME-EARLY'})]}}));
  await page.getByRole('button', {name: 'Search SPHEREx Observations'}).click();
  await expect(explorer.getByTestId('time-slider')).toBeDisabled();
  await expect(explorer.getByRole('button', {name: 'Previous observation'})).toBeDisabled();
  await expect(explorer.getByRole('button', {name: 'Next observation'})).toBeDisabled();
  await expect(explorer.getByTestId('time-slider-image')).toHaveAttribute('src', /synthetic-time-early\/preview$/);
  await expect(explorer).toContainText('Step 1 of 1');
});
