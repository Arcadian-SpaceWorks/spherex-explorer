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
  await compare.getByRole('button', {name: 'Find Changes'}).click();
  await expect(compare.getByTestId('compare-result')).toBeVisible({timeout: 60000});
  expect(posted[0]).toEqual({a: {demo_image_id: a.image_id}, b: {demo_image_id: b.image_id},
    ra: barnard.ra, dec: barnard.dec, size_deg: 0.3, mode: 'time'});
  await expect(compare.getByText('Preloaded real observations', {exact: true})).toBeVisible();
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
  await compare.getByRole('button', {name: 'Find Changes'}).click();
  await expect(compare.getByTestId('compare-result')).toBeVisible({timeout: 60000});
  await expect(compare.getByRole('button', {name: 'Difference'})).toBeDisabled();
  await pickButton(page, row(comet, '2025W50_2A_0712_4', 5), 'A').click();
  await expect(compare.getByRole('button', {name: 'Time (suggested)'})).toHaveAttribute('aria-pressed', 'true');
  await compare.getByRole('button', {name: 'Find Changes'}).click();
  await expect(compare.getByTestId('compare-result')).toBeVisible({timeout: 60000});
  await expect(compare.getByTestId('difference-unavailable')).toBeVisible();
  // Choosing another target clears the picks.
  await page.getByLabel('Preloaded target').selectOption('m31');
  await expect(compare.getByTestId('compare-slot-a')).toContainText('Not chosen');
  expect(forbidden).toEqual([]);
});
