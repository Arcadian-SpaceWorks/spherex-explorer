import { test, expect } from '@playwright/test';

const row = extra => ({id: 1, kind: 'image', label: 'SYNTHETIC-1 · D3', detail: '0.3° cutout', stage: 'downloading', source: 'AWS mirror', bytes: 0, total: null, state: 'active', elapsed_seconds: 1, ...extra});

async function serve(page, jobsRef) {
  await page.route('**/api/images/progress', route => route.fulfill({json: {jobs: jobsRef.current}}));
}

test('the panel stays on screen with measured progress, wherever you scroll', async ({page}) => {
  const jobs = {current: [row({bytes: 35800000, total: 71600000})]};
  await serve(page, jobs);
  await page.goto('/', {waitUntil: 'domcontentloaded'});
  const tray = page.getByRole('complementary', {name: 'Downloads'});
  await expect(tray).toContainText('1 in progress');
  await expect(tray).toContainText('35.8 MB of 71.6 MB');
  await expect(tray.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '50');
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await expect(tray).toBeInViewport();

  jobs.current = [row({source: 'IRSA', bytes: 2300000})];  // IRSA cutouts state no size.
  await expect(tray).toContainText('2.3 MB so far');
  await expect(tray.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow');

  jobs.current = [row({state: 'done', stage: 'decoding'})];
  await expect(tray).toContainText('Ready');
  jobs.current = [];
  await expect(tray).toHaveCount(0);
});

test('the panel never blocks clicks and fits a phone', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  const jobs = {current: [1, 2, 3, 4, 5, 6].map(id => row({id, bytes: 10, total: 100}))};
  await serve(page, jobs);
  await page.goto('/', {waitUntil: 'domcontentloaded'});
  const tray = page.getByRole('complementary', {name: 'Downloads'});
  await expect(tray).toContainText('and 2 more');
  await expect(tray.getByTestId('download-job')).toHaveCount(4);
  expect(await tray.evaluate(element => getComputedStyle(element).pointerEvents)).toBe('none');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test('Demo Mode downloads nothing, so it never asks for progress', async ({page}) => {
  const asked = [];
  page.on('request', request => {if (request.url().endsWith('/api/images/progress')) asked.push(request.url());});
  await page.goto('/?mode=demo', {waitUntil: 'networkidle'});
  await page.waitForTimeout(1500);
  expect(asked).toEqual([]);
  await expect(page.getByRole('complementary', {name: 'Downloads'})).toHaveCount(0);
});
