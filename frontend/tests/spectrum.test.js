import test from 'node:test';
import assert from 'node:assert/strict';
import { describeFeature, fluxDomain, formatFlux, logTicks, niceTicks, outcomeSummary, redshiftedLines, seasonSeries,
  SEASON_COLORS, usablePoints, wideRange } from '../src/spectrum.js';

const season = (index, start, end, measured = 10) => ({index, start_utc: `${start}T00:00:00`, end_utc: `${end}T00:00:00`, measured});

test('only measured points with a wavelength are plotted', () => {
  const points = [{status: 'ok', wavelength_um: 1.2, flux_mjy: 3}, {status: 'saturated'}, {status: 'ok', wavelength_um: null, flux_mjy: 1}, {status: 'ok', wavelength_um: 2, flux_mjy: -0.1}];
  assert.deepEqual(usablePoints(points).map(point => point.wavelength_um), [1.2, 2]);
  assert.deepEqual(usablePoints(undefined), []);
});

test('seasons keep the three validated colours; older seasons fold into one neutral series', () => {
  const three = seasonSeries([season(0, '2025-08-01', '2025-08-15'), season(1, '2026-02-01', '2026-02-10'), season(2, '2026-08-01', '2026-08-01')]);
  assert.deepEqual(three.map(item => item.color), SEASON_COLORS);
  assert.equal(three[0].label, '1 Aug 2025 – 15 Aug 2025');
  assert.equal(three[2].label, '1 Aug 2026');
  const five = seasonSeries([0, 1, 2, 3, 4].map(index => season(index, `2025-0${index + 1}-01`, `2025-0${index + 1}-09`)));
  assert.equal(five.length, 4);
  assert.deepEqual(five[0].indexes, [0, 1]);
  assert.equal(five[0].measured, 20);
  assert.match(five[0].label, /^2 earlier seasons/);
  assert.deepEqual(five.slice(1).map(item => item.color), SEASON_COLORS);
  assert.deepEqual(seasonSeries(undefined), []);
});

test('the flux axis starts at zero, keeps negatives visible and switches to log only for wide ranges', () => {
  const flat = [1, 2, 3, 4, 5, 6].map(flux_mjy => ({flux_mjy}));
  assert.equal(fluxDomain(flat, false)[0], 0);
  assert.ok(fluxDomain(flat, false)[1] > 6);
  assert.ok(fluxDomain([{flux_mjy: -1}, {flux_mjy: 4}], false)[0] < -1);
  assert.equal(wideRange(flat), false);
  assert.equal(wideRange([...flat, {flux_mjy: 500}]), true);
  const [low, high] = fluxDomain([...flat, {flux_mjy: 500}, {flux_mjy: -2}], true);
  assert.ok(low > 0 && low < 1 && high > 500);
  assert.deepEqual(fluxDomain([], true), [0.1, 10]);
});

test('ticks are round numbers', () => {
  assert.deepEqual(niceTicks([0, 520]), [0, 200, 400]);
  assert.deepEqual(niceTicks([0, 0.9]), [0, 0.2, 0.4, 0.6, 0.8]);
  assert.deepEqual(logTicks([0.5, 2000]), [1, 10, 100, 1000]);
});

test('flux values read in sensible units', () => {
  assert.equal(formatFlux(473.5), '474 mJy');
  assert.equal(formatFlux(2.306), '2.31 mJy');
  assert.equal(formatFlux(0.0421), '42.1 µJy');
  assert.equal(formatFlux(1503), '1.50 Jy');
  assert.equal(formatFlux(NaN), '—');
});

test('redshift ruler places only the lines that fall inside the SPHEREx range', () => {
  const lines = redshiftedLines(1.337);
  const halpha = lines.find(line => line.label === 'Hα');
  assert.ok(Math.abs(halpha.observed - 1.534) < 0.002);
  assert.ok(lines.every(line => line.observed >= 0.7 && line.observed <= 5.1));
  assert.equal(lines.some(line => line.label === 'Brα'), false);
  assert.deepEqual(redshiftedLines(NaN), []);
  assert.deepEqual(redshiftedLines(-1), []);
});

test('findings are worded from the measurement', () => {
  const co2 = {center: 4.27};
  assert.equal(describeFeature({kind: 'absorption', strength: 0.63, optical_depth: 1.0}, co2), '63% of the light is absorbed at 4.27 µm (optical depth 1.00).');
  assert.equal(describeFeature({kind: 'absorption', strength: 1.01, optical_depth: 3.2, optical_depth_is_lower_limit: true}, co2), '100% of the light is absorbed at 4.27 µm (the band bottoms out: optical depth above 3.2).');
  assert.equal(describeFeature({kind: 'emission', strength: 38.6}, co2), '39.6× the continuum at 4.27 µm.');
  assert.equal(describeFeature({kind: 'emission', strength: 0.4}, co2), '40% above the continuum at 4.27 µm.');
  assert.match(describeFeature({kind: 'emission', strength: null}, co2), /too faint/);
});

test('rejected exposures are summarised with their reasons', () => {
  assert.deepEqual(outcomeSummary({ok: 100, flagged: 7, saturated: 90, edge: 0}), ['90 saturated', '7 flagged pixels']);
  assert.deepEqual(outcomeSummary(undefined), []);
});
