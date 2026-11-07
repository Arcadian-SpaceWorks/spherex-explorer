import { test, expect } from '@playwright/test';
import fs from 'node:fs';

// TEST DATA: synthetic rows and mocked /api/compare responses. No IRSA access.
const fixture = JSON.parse(fs.readFileSync(new URL('../fixtures/image.json', import.meta.url)));
const png = fs.readFileSync(new URL('../fixtures/synthetic.png', import.meta.url));
const row = (obs_id, band, observed_at_utc) => ({obs_id, energy_bandpassname: band, obs_collection: 'test-only', observed_at_utc,
  s_ra: 10.68, s_dec: 41.27, t_exptime: 113, em_min: null, em_max: null, access_format: 'application/x-votable+xml;content=datalink',
  access_url: `https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=synthetic-${obs_id}-${band}`});
const rows = [
  row('SYNTHETIC-JUL', 'SPHEREx-D1', '2026-07-10T00:01:31.000'),
  row('SYNTHETIC-JAN', 'SPHEREx-D1', '2026-01-01T06:00:12.000'),
  row('SYNTHETIC-JAN', 'SPHEREx-D4', '2026-01-01T06:00:12.000'),
  row('SYNTHETIC-2025', 'SPHEREx-D1', '2025-07-09T14:56:47.000'),
];
const frame = (r, role, wavelength) => ({role, obs_id: r.obs_id, band: r.energy_bandpassname, detector: Number(r.energy_bandpassname.at(-1)),
  observed_at_utc: r.observed_at_utc, wavelength_um: wavelength, bandwidth_um: .01,
  diagnostics: {core_median: 50.9, sky_level: 1.2, zodi_median: .15}, provenance: {source: 'irsa_cutout'}});
const reason = (code, severity, detail) => ({code, severity, detail, values: {}});

function compareResult({a, b, mode}) {
  const ra = rows.find(r => r.access_url === a.access_url), rb = rows.find(r => r.access_url === b.access_url);
  const wl = r => r.energy_bandpassname === 'SPHEREx-D4' ? 2.98 : r.obs_id === 'SYNTHETIC-2025' ? .750 : r.obs_id === 'SYNTHETIC-JAN' ? .8946 : .8935;
  const delta = Math.abs(wl(ra) - wl(rb));
  let decision = 'ACCEPT', reasons = [reason('wavelength_match', 'info', 'Target wavelengths agree within 0.001 um.')];
  if (mode === 'wavelength') reasons = [reason('no_cross_wavelength_difference', 'info', 'Images at different wavelengths are shown side by side or blinked, never subtracted.')];
  else if (delta > .02) {decision = 'WARN'; reasons = [reason('wavelength_mismatch', 'warn', `The target was seen at wavelengths ${delta.toFixed(3)} um apart (limit 0.02 um). Brightness differences may come from wavelength, not time. Blink only.`)];}
  const allowed = mode === 'time' && decision === 'ACCEPT';
  const id = (allowed ? 'a' : mode === 'wavelength' ? 'c' : 'b').repeat(64);
  return {compare_id: id, decision, cache_hit: false, overlap_fraction: .981,
    validation: {mode, decision, difference_allowed: allowed, wavelength_delta_um: delta, time_separation_hours: 4554, overlap_fraction: .981, reasons},
    frames: [frame(ra, 'a', wl(ra)), frame(rb, 'b', wl(rb))], grid: {shape: [176, 176], north_up: true},
    stretch: {shared: allowed}, difference: allowed ? {robust_noise: .199, display: {meaning: 'Mid-gray is no change; lighter means brighter in B, darker means fainter in B.'}} : null,
    previews: {a: `/api/compare/${id}/a.png`, b: `/api/compare/${id}/b.png`, difference: allowed ? `/api/compare/${id}/difference.png` : null},
    notes: ['Real NASA/IPAC IRSA SPHEREx data, downloaded through this server\'s image cache. No motion, variability or discovery is claimed.',
      allowed ? 'A and B share one brightness scale, so their brightness can be compared.'
        : 'A and B each have their own brightness scale; do not compare their brightness by eye.']};
}

async function setup(page, {compare} = {}) {
  const posted = [];
  await page.route('**/api/observations?**', route => route.fulfill({json: {status: 'live', ra: 10.6847, dec: 41.2687, count: rows.length, truncated: false, observations: rows}}));
  await page.route('**/api/images', route => route.fulfill({json: fixture}));
  await page.route('**/api/images/*/preview', route => route.fulfill({contentType: 'image/png', body: png}));
  await page.route('**/api/compare/*/*.png', route => route.fulfill({contentType: 'image/png', body: png}));
  await page.route('**/api/compare', async route => {
    const body = route.request().postDataJSON();
    posted.push(body);
    return compare ? compare(route, body) : route.fulfill({json: compareResult(body)});
  });
  await page.goto('/', {waitUntil: 'domcontentloaded'});
  await page.getByRole('button', {name: 'Search SPHEREx Observations'}).click();
  await expect(page.getByRole('button', {name: 'View Image'})).toHaveCount(rows.length);
  return posted;
}
const pickButton = (page, r, role) => page.getByRole('button', {name: `Set ${r.obs_id} ${r.energy_bandpassname} as ${role} for comparison`});
const panel = page => page.getByRole('region', {name: 'Image comparison'});

test('pick A and B, compare in time mode, switch side by side, blink and difference', async ({page}) => {
  const posted = await setup(page);
  const compare = panel(page);
  await expect(compare.getByRole('button', {name: 'Compare A and B'})).toBeDisabled();
  await pickButton(page, rows[1], 'A').click();
  await pickButton(page, rows[0], 'B').click();
  await expect(compare.getByTestId('compare-slot-a')).toContainText('SYNTHETIC-JAN');
  await expect(compare.getByTestId('compare-slot-b')).toContainText('SYNTHETIC-JUL');
  await expect(compare.getByRole('button', {name: 'Time (suggested)'})).toHaveAttribute('aria-pressed', 'true');
  await compare.getByRole('button', {name: 'Compare A and B'}).click();
  await expect(compare.getByTestId('compare-verdict')).toContainText('ACCEPT');
  expect(posted[0]).toEqual({a: {access_url: rows[1].access_url}, b: {access_url: rows[0].access_url},
    ra: 210.80227, dec: 54.34895, size_deg: 0.3, mode: 'time'});
  await expect(compare.getByTestId('compare-image-a')).toBeVisible();
  await expect(compare.getByTestId('compare-image-b')).toBeVisible();
  await expect(compare.getByTestId('compare-legend')).toContainText('Violet marks masked pixels');
  await expect(compare).toContainText('No motion, variability or discovery is claimed');
  await compare.getByRole('button', {name: 'Blink'}).click();
  const blink = compare.getByTestId('compare-blink');
  await compare.getByRole('button', {name: 'Show B'}).click();
  await expect(blink).toHaveAttribute('data-shown', 'b');
  await expect(compare.getByRole('button', {name: 'Play blink'})).toBeVisible();
  await compare.getByRole('button', {name: 'Play blink'}).click();
  await expect(blink).toHaveAttribute('data-shown', 'a', {timeout: 8000});  // Auto-blinks every second.
  await compare.getByRole('button', {name: 'Difference'}).click();
  await expect(compare.getByTestId('compare-image-difference')).toBeVisible();
  await expect(compare).toContainText('not a validated change');
});

test('wavelength mismatch gives WARN with the difference tab disabled and separate scales', async ({page}) => {
  await setup(page);
  const compare = panel(page);
  await pickButton(page, rows[3], 'A').click();
  await pickButton(page, rows[1], 'B').click();
  await compare.getByRole('button', {name: 'Compare A and B'}).click();
  await expect(compare.getByTestId('compare-verdict')).toContainText('WARN');
  await expect(compare.getByTestId('compare-verdict')).toContainText('Blink only');
  await expect(compare).toContainText('0.145 um apart');
  await expect(compare.getByRole('button', {name: 'Difference'})).toBeDisabled();
  await expect(compare.getByTestId('difference-unavailable')).toContainText('Blink only');
  await expect(compare).toContainText('own brightness scale');
});

test('two detectors of one exposure suggest wavelength mode and are never subtracted', async ({page}) => {
  const posted = await setup(page);
  const compare = panel(page);
  await pickButton(page, rows[1], 'A').click();
  await pickButton(page, rows[2], 'B').click();
  await expect(compare.getByRole('button', {name: 'Wavelength (suggested)'})).toHaveAttribute('aria-pressed', 'true');
  await compare.getByRole('button', {name: 'Compare A and B'}).click();
  await expect(compare.getByTestId('compare-verdict')).toContainText('Side by side');
  expect(posted[0].mode).toBe('wavelength');
  await expect(compare.getByRole('button', {name: 'Difference'})).toBeDisabled();
  await expect(compare.getByTestId('difference-unavailable')).toContainText('never subtracted');
  // Switching to time mode for two detectors warns before anything is sent.
  await compare.getByRole('button', {name: 'Time', exact: true}).click();
  await expect(compare.getByRole('note').filter({hasText: 'Different detectors'})).toBeVisible();
  await expect(compare.getByTestId('compare-result')).toHaveCount(0);
});

test('picking, moving, swapping and clearing keep A and B distinct', async ({page}) => {
  await setup(page);
  const compare = panel(page);
  await pickButton(page, rows[0], 'A').click();
  await pickButton(page, rows[0], 'B').click();  // Moves the row from A to B.
  await expect(compare.getByTestId('compare-slot-a')).toContainText('Not chosen');
  await expect(compare.getByTestId('compare-slot-b')).toContainText('SYNTHETIC-JUL');
  await pickButton(page, rows[1], 'A').click();
  await compare.getByRole('button', {name: 'Swap A and B'}).click();
  await expect(compare.getByTestId('compare-slot-a')).toContainText('SYNTHETIC-JUL');
  await expect(compare.getByTestId('compare-slot-b')).toContainText('SYNTHETIC-JAN');
  await compare.getByRole('button', {name: 'Remove A'}).click();
  await expect(compare.getByTestId('compare-slot-a')).toContainText('Not chosen');
  await expect(compare.getByRole('button', {name: 'Compare A and B'})).toBeDisabled();
  // A new search clears both picks.
  await page.getByRole('button', {name: 'Search SPHEREx Observations'}).click();
  await expect(compare.getByTestId('compare-slot-b')).toContainText('Not chosen');
});

test('errors are explicit and the comparison can be retried; stop waiting cancels', async ({page}) => {
  let calls = 0;
  await setup(page, {compare: async (route, body) => {
    calls += 1;
    if (calls === 1) return route.fulfill({status: 502, json: {status: 'unavailable', code: 'image_unavailable', message: 'IRSA could not deliver this image. Please retry.'}});
    if (calls === 2) {await new Promise(resolve => setTimeout(resolve, 4000)); return route.fulfill({json: compareResult(body)}).catch(() => {});}
    return route.fulfill({json: compareResult(body)});
  }});
  const compare = panel(page);
  await pickButton(page, rows[1], 'A').click();
  await pickButton(page, rows[0], 'B').click();
  await compare.getByRole('button', {name: 'Compare A and B'}).click();
  await expect(compare.getByRole('alert')).toContainText('IRSA could not deliver this image');
  await compare.getByRole('button', {name: 'Compare again'}).click();
  await expect(compare.getByTestId('download-progress')).toBeVisible();
  await compare.getByRole('button', {name: 'Stop waiting'}).click();
  await expect(compare.getByTestId('download-progress')).toHaveCount(0);
  await expect(compare.getByTestId('compare-result')).toHaveCount(0);
  await compare.getByRole('button', {name: 'Compare A and B'}).click();  // Nothing shown after stopping.
  await expect(compare.getByTestId('compare-verdict')).toContainText('ACCEPT');
});

test('demo mode has no compare buttons; the panel fits a phone screen', async ({page}) => {
  await setup(page);
  await pickButton(page, rows[1], 'A').click();
  await pickButton(page, rows[0], 'B').click();
  await panel(page).getByRole('button', {name: 'Compare A and B'}).click();
  await expect(panel(page).getByTestId('compare-verdict')).toContainText('ACCEPT');
  await page.setViewportSize({width: 390, height: 844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.getByRole('radio', {name: /Demo Mode/}).check();
  await expect(page.getByRole('button', {name: 'View Image'}).first()).toBeVisible();
  await expect(page.getByRole('button', {name: /for comparison$/})).toHaveCount(0);
  await expect(panel(page)).toHaveCount(0);
});
