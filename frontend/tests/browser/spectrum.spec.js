import { test, expect } from '@playwright/test';

// Synthetic API replies for the browser only: an icy spectrum measured in two seasons.
const point = (wavelength, flux, epoch) => ({obs_id: `2025W30_1A_${Math.round(wavelength * 1000)}_${epoch}`, detector: wavelength < 4.42 ? 5 : 6,
  mjd: 60900 + epoch * 180, utc: epoch ? '2026-02-20T00:00:00' : '2025-08-24T00:00:00', collection: 'spherex_qr2', status: 'ok',
  wavelength_um: wavelength, bandwidth_um: 0.04, flux_mjy: flux, flux_err_mjy: 0.2, flag_names: [], epoch, ra: 69.97458, dec: 26.05278});
const points = [];
for (let wavelength = 3.9; wavelength < 4.95; wavelength += 0.03) for (const epoch of [0, 1])
  points.push(point(wavelength + epoch * 0.01, 20 * (1 - 0.8 * Math.exp(-(((wavelength - 4.27) / 0.035) ** 2))), epoch));
points.push({...point(4.1, 0, 0), status: 'saturated', wavelength_um: null, flux_mjy: null, flux_err_mjy: null, flag_names: ['OVERFLOW']});
const method = {source: 'Synthetic browser fixture', photometry: 'Forced circular aperture', background: 'Local', uncertainty: 'Variance', wavelength: 'WCS-WAVE', rejected: 'Flagged', limits: ['No aperture correction: test fixture.']};
const season = (index, day) => ({index, start_mjd: 0, end_mjd: 0, start_utc: `${day}T00:00:00`, end_utc: `${day}T00:00:00`, exposures: 36, measured: 35});
const job = state => ({id: 'job1', state, message: '', request: {kind: 'position', ra: 69.97458, dec: 26.05278, limit: 600}, total: points.length,
  done: state === 'done' ? points.length : 10, available: points.length, truncated: false, megabytes_read: 12.5, elapsed_s: 3,
  points: state === 'done' ? points : points.slice(0, 10), method,
  analysis: {counts: {ok: points.length - 1, saturated: 1}, seasons: [season(0, '2025-08-24'), season(1, '2026-02-20')], binned: [], mixed_seasons: false, seasons_scaled: false,
    median_snr: 90, features_by_season: [],
    features: [{id: 'co2', status: 'detected', kind: 'absorption', strength: 0.8, optical_depth: 1.61, optical_depth_is_lower_limit: false, significance: -40, points: {core: 6, left: 8, right: 4}},
      {id: 'co', status: 'not_detected', kind: null, strength: 0.01, significance: 0.4, points: {core: 4, left: 5, right: 5}},
      {id: 'h2o_ice', status: 'not_measurable', points: {core: 0, left: 0, right: 0}}],
    variability: {status: 'steady', amplitude: 0.01, significance: 1.2, floor: 0.08, reference: 0, seasons: [
      {index: 0, start_utc: '2025-08-24T00:00:00', end_utc: '2025-08-24T00:00:00', relative_flux: 1, relative_flux_err: 0, n: 35, reference: true, bands: []},
      {index: 1, start_utc: '2026-02-20T00:00:00', end_utc: '2026-02-20T00:00:00', relative_flux: 0.99, relative_flux_err: 0.01, n: 30, bands: [{detector: 5, relative_flux: 0.99, relative_flux_err: 0.01, n: 20}]}]}}});
const features = {thresholds: {sigma: 5, strength: 0.08, variability: 0.08, season_gap_days: 20}, method, moving_targets: [], features: [
  {id: 'h2o_ice', label: 'Water ice', formula: 'H2O', center: 3.05, core: [2.9, 3.2], kinds: ['absorption'], group: 'Ices', meaning: 'Frozen water.', caveat: ''},
  {id: 'co2', label: 'Carbon dioxide', formula: 'CO2', center: 4.27, core: [4.22, 4.31], kinds: ['absorption', 'emission'], group: 'Ices', meaning: 'CO2 ice on dust grains.', caveat: 'Cool stars differ.'},
  {id: 'co', label: 'Carbon monoxide ice', formula: 'CO', center: 4.67, core: [4.645, 4.7], kinds: ['absorption'], group: 'Ices', meaning: 'CO ice.', caveat: ''}]};

test('measuring a position fills in a spectrum, names the bands found and says what was rejected', async ({page}) => {
  let polls = 0, started = null;
  await page.route('**/api/spectrum/features', route => route.fulfill({json: features}));
  await page.route('**/api/spectrum/reference?*', route => route.fulfill({json: {status: 'live', photometry: [{survey: 'AllWISE', band: 'W2', wavelength_um: 4.6028, magnitude: 9.9, flux_mjy: 19, flux_err_mjy: 0.4, separation_arcsec: 0.5}]}}));
  await page.route('**/api/spectrum', route => {started = route.request().postDataJSON(); return route.fulfill({status: 202, json: {id: 'job1'}});});
  await page.route('**/api/spectrum/job1', route => route.fulfill({json: job(++polls < 2 ? 'running' : 'done')}));
  await page.goto('/');
  const panel = page.getByTestId('spectrum-panel');
  await expect(panel.getByRole('heading', {name: 'What is this point of sky made of?'})).toBeVisible();
  await panel.getByRole('button', {name: 'Protostar L1527'}).click();
  await expect(panel.getByTestId('spectrum-progress')).toContainText('Measured 10 of');
  await expect(panel.getByTestId('spectrum-title')).toContainText('Protostar L1527');
  await expect(panel.getByTestId('spectrum-progress')).toHaveCount(0);
  expect(started).toEqual({ra: 69.97458, dec: 26.05278});
  await expect(page.getByTestId('selected-ra')).toContainText('69.974580');
  await expect(panel.getByTestId('spectrum-svg').locator('.spectrum-point')).toHaveCount(points.length - 1);
  await expect(panel.getByTestId('band-co2')).toBeVisible();
  await expect(panel.getByTestId('finding-co2')).toContainText('80% of the light is absorbed at 4.27 µm (optical depth 1.61)');
  await expect(panel).toContainText('Looked for and not found: Carbon monoxide ice.');
  await expect(panel).toContainText('Not enough exposures to test: Water ice.');
  await expect(panel).toContainText('Not plotted: 1 saturated.');
  await expect(panel.getByTestId('spectrum-change')).toContainText('Steady: seasons agree within 1%');
  await expect(panel.locator('.spectrum-legend')).toContainText('24 Aug 2025');
  await expect(panel.locator('.spectrum-legend')).toContainText('2MASS / WISE catalogue');
  // Hovering reads out the nearest exposure; the table and the CSV carry every value.
  const box = await panel.getByTestId('spectrum-svg').boundingBox();
  await page.mouse.move(box.x + box.width * 0.8, box.y + box.height * 0.3);
  await expect(panel.locator('.spectrum-tooltip')).toContainText('µm · detector');
  await panel.getByText('Table of measurements and download').click();
  await expect(panel.locator('.spectrum-scroll tbody tr')).toHaveCount(points.length - 1);
  const download = page.waitForEvent('download');
  await panel.getByTestId('spectrum-csv').click();
  expect((await download).suggestedFilename()).toMatch(/^spherex-spectrum-.*\.csv$/);
  // Choosing another sky position clears the spectrum, so it never describes the wrong place.
  await page.locator('#ra').fill('10'); await page.locator('#dec').fill('20');
  await page.getByRole('button', {name: /Go To Coordinates/}).click();
  await expect(panel.getByTestId('spectrum-title')).toHaveCount(0);
});

test('an archive failure is reported and nothing is plotted', async ({page}) => {
  await page.route('**/api/spectrum/features', route => route.fulfill({json: features}));
  await page.route('**/api/spectrum', route => route.fulfill({status: 202, json: {id: 'job1'}}));
  await page.route('**/api/spectrum/job1', route => route.fulfill({json: {...job('running'), state: 'failed', total: 0, done: 0, points: [], message: 'IRSA TAP could not be reached or timed out. Please retry.'}}));
  await page.goto('/');
  await page.getByTestId('measure-spectrum').click();
  await expect(page.getByTestId('spectrum-panel').getByRole('alert')).toContainText('IRSA TAP could not be reached');
  await expect(page.getByTestId('spectrum-svg')).toHaveCount(0);
});

test('demo mode measures the preloaded comet frames locally and finds carbon dioxide gas', async ({page}) => {
  await page.goto('/?mode=demo');
  await page.selectOption('#demo-target', '3i-atlas');
  const panel = page.getByTestId('spectrum-panel');
  await expect(panel.getByTestId('spectrum-title')).toContainText('3I/ATLAS', {timeout: 60000});
  await expect(panel.getByTestId('finding-co2')).toContainText('emission');
  await expect(panel).toContainText('Moving target: each exposure is measured at the position predicted for that moment');
  await expect(panel.getByTestId('measure-spectrum')).toHaveCount(0);
});
