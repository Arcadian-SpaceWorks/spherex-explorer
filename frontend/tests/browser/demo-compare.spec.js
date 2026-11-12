import { test, expect } from '@playwright/test';
import fs from 'node:fs';

// Real preloaded frames and the real comparison backend; external and live archive requests are blocked.
const manifest = JSON.parse(fs.readFileSync(new URL('../../public/demo/manifest.json', import.meta.url)));
const barnard = manifest.targets.find(t => t.id === 'barnard');
const row = (target, obsId, detector) => target.observations.find(o => o.obs_id === obsId && o.detector === detector);
const pickButton = (page, r, role) => page.getByRole('button', {name: `Set ${r.obs_id} SPHEREx-D${r.detector} as ${role} for comparison`});
const panel = page => page.getByRole('region', {name: 'Image comparison'});

async function demo(page, targetId) {
  const forbidden = [], posted = [];
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (!['localhost', '127.0.0.1'].includes(url.hostname) || ['/api/images', '/api/observations'].includes(url.pathname)) {
      forbidden.push(url.href); return route.abort();
    }
    if (url.pathname === '/api/compare') posted.push(route.request().postDataJSON());
    return route.continue();
  });
  await page.goto('/?mode=demo');
  await page.getByLabel('Preloaded target').selectOption(targetId);
  return {forbidden, posted};
}

test('Barnard’s Star: a wavelength-matched pair a year apart is differenced from local files', async ({page}) => {
  const {forbidden, posted} = await demo(page, 'barnard');
  const a = row(barnard, '2025W33_2C_0321_1', 3), b = row(barnard, '2026W34_1A_0176_2', 3);
  await pickButton(page, a, 'A').click();
  // The ≈ A badge marks same-detector frames within 0.02 um of A at the target.
  await expect(page.locator('.observations tr', {hasText: b.obs_id}).locator('.wavelength-badge')).toHaveText('≈ A');
  await pickButton(page, b, 'B').click();
  const compare = panel(page);
  await expect(compare).toContainText('compared locally from their original FITS');
  await compare.getByRole('button', {name: 'Compare A and B'}).click();
  await expect(compare.getByTestId('compare-verdict')).toContainText('ACCEPT', {timeout: 60000});
  expect(posted[0]).toEqual({a: {demo_image_id: a.image_id}, b: {demo_image_id: b.image_id},
    ra: barnard.ra, dec: barnard.dec, size_deg: 0.3, mode: 'time'});
  await expect(compare.getByText('Preloaded data', {exact: true})).toBeVisible();
  await expect(compare).toContainText('preloaded in the local demo bundle; no network was used');
  await compare.getByRole('button', {name: 'Difference'}).click();
  const difference = compare.getByTestId('compare-image-difference');
  await expect(difference).toBeVisible();
  await expect.poll(() => difference.evaluate(img => img.complete && img.naturalWidth)).toBe(176);
  expect(forbidden).toEqual([]);
});

test('3I/ATLAS: two bands of one exposure side by side; hours apart is blink only', async ({page}) => {
  const comet = manifest.targets.find(t => t.id === '3i-atlas');
  const {forbidden} = await demo(page, '3i-atlas');
  const compare = panel(page);
  await pickButton(page, row(comet, '2025W50_2A_0698_1', 2), 'A').click();
  await pickButton(page, row(comet, '2025W50_2A_0698_1', 5), 'B').click();
  await expect(compare.getByRole('button', {name: 'Wavelength (suggested)'})).toHaveAttribute('aria-pressed', 'true');
  await compare.getByRole('button', {name: 'Compare A and B'}).click();
  await expect(compare.getByTestId('compare-verdict')).toContainText('Side by side', {timeout: 60000});
  await expect(compare.getByRole('button', {name: 'Difference'})).toBeDisabled();
  await pickButton(page, row(comet, '2025W50_2A_0712_4', 5), 'A').click();
  await expect(compare.getByRole('button', {name: 'Time (suggested)'})).toHaveAttribute('aria-pressed', 'true');
  await compare.getByRole('button', {name: 'Compare A and B'}).click();
  await expect(compare.getByTestId('compare-verdict')).toContainText('Blink only', {timeout: 60000});
  await expect(compare.getByTestId('difference-unavailable')).toBeVisible();
  // Choosing another target clears the picks.
  await page.getByLabel('Preloaded target').selectOption('m31');
  await expect(compare.getByTestId('compare-slot-a')).toContainText('Not chosen');
  expect(forbidden).toEqual([]);
});

test('Barnard’s Star: clicking the star in A and B measures its motion against Gaia', async ({page}) => {
  const {forbidden} = await demo(page, 'barnard');
  const a = row(barnard, '2025W33_2C_0321_1', 3), b = row(barnard, '2026W34_1A_0176_2', 3);
  await pickButton(page, a, 'A').click();
  await pickButton(page, b, 'B').click();
  const compare = panel(page);
  await compare.getByRole('button', {name: 'Compare A and B'}).click();
  await expect(compare.getByTestId('compare-verdict')).toContainText('ACCEPT', {timeout: 60000});
  const measure = compare.getByTestId('motion-measure');
  await expect(measure.getByTestId('measure-instruction')).toContainText('Click the object in image A');
  // The star sits at the centre of the grid; click a little off it, as a person would.
  for (const role of ['a', 'b']) {
    const image = measure.getByTestId(`measure-image-${role}`);
    await expect.poll(() => image.evaluate(img => img.complete && img.naturalWidth)).toBe(176);
    const box = await image.boundingBox();
    await image.click({position: {x: box.width * 0.51, y: box.height * 0.49}});
  }
  const result = measure.getByTestId('measure-result');
  await expect(result).toBeVisible({timeout: 30000});
  await expect(result.getByTestId('measure-rate')).toContainText('″ per year');
  await expect(result.getByTestId('measure-shift')).toContainText('toward the north');
  await expect(result.getByTestId('measure-summary')).toContainText('agrees with the prediction');
  await expect(result.getByTestId('measure-prediction')).toContainText('10.4″ per year');
  await expect(result.getByTestId('measure-warnings')).toContainText('Saturated object');
  await expect(result.getByTestId('candidate-id')).toHaveText(/^SKT-\d{8}-[0-9A-F]{8}$/);
  await expect(result).toContainText('not an official designation');
  const download = page.waitForEvent('download');
  await result.getByRole('button', {name: 'Download candidate record (JSON)'}).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^SKT-\d{8}-[0-9A-F]{8}\.json$/);
  const record = JSON.parse(fs.readFileSync(await file.path(), 'utf8'));
  expect(record.prediction.rate_arcsec_per_year).toBeCloseTo(10.39, 1);
  expect(record.claim).toContain('Not a confirmed detection');
  await measure.getByRole('button', {name: 'Clear points'}).click();
  await expect(measure.getByTestId('measure-result')).toHaveCount(0);
  expect(forbidden).toEqual([]);
});
