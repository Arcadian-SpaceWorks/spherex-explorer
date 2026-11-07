/** Local bundle adapter. No IRSA requests or synthetic fallback. */
import { chronologicalFrames, parseUtc } from './timeline.js';

const hash = /^[a-f0-9]{64}$/;
const asset = (value, id, name) => value === `/demo/assets/${id}/${name}`;
export function validateDemoManifest(data) {
  if (data?.schema_version !== 1 || typeof data.science_note !== 'string' || !Array.isArray(data.targets) || data.targets.length < 2 || data.targets.length > 3) {
    throw new Error('Invalid demo manifest schema. Prepare and validate the demo bundle.');
  }
  const ids = new Set(), images = new Set();
  for (const target of data.targets) {
    if (!/^[a-z0-9-]+$/.test(target.id) || ids.has(target.id) || !target.name || !target.coordinate_source?.startsWith('https://') ||
        !Number.isFinite(target.ra) || target.ra < 0 || target.ra >= 360 || !Number.isFinite(target.dec) || Math.abs(target.dec) > 90 ||
        !['ready', 'missing'].includes(target.status) || !Array.isArray(target.observations) ||
        (target.status === 'ready') !== Boolean(target.observations.length) || (target.status === 'missing' && !target.missing_reason)) {
      throw new Error('Invalid or duplicate demo target.');
    }
    ids.add(target.id);
    for (const row of target.observations) {
      let source, access;
      try {source = new URL(row.source_url); access = new URL(row.access_url);} catch {throw new Error('Invalid demo source URL.');}
      if (!hash.test(row.image_id) || images.has(row.image_id) || !row.obs_id || /synthetic|fixture|test-only|demo/i.test(row.obs_id) ||
          !row.observed_at_utc?.endsWith('Z') || parseUtc(row.observed_at_utc) == null || !Number.isInteger(row.detector) || row.detector < 1 || row.detector > 6 ||
          [source, access].some(url => url.protocol !== 'https:' || url.hostname !== 'irsa.ipac.caltech.edu' || url.username || url.password) ||
          !source.pathname.startsWith('/ibe/data/spherex/') || !source.searchParams.has('center') || !source.searchParams.has('size') ||
          !asset(row.preview_path, row.image_id, 'preview.png') || !asset(row.metadata_path, row.image_id, 'metadata.json') || !asset(row.fits_path, row.image_id, 'original.fits') ||
          !['fits_sha256', 'preview_sha256', 'metadata_sha256'].every(key => hash.test(row[key])) || !row.provenance?.verification || !row.provenance?.renderer) {
        throw new Error('Invalid demo observation or unsafe asset path.');
      }
      images.add(row.image_id);
    }
  }
  return data;
}

export async function loadDemoManifest({signal, fetchImpl = fetch} = {}) {
  const response = await fetchImpl('/demo/manifest.json', {signal});
  if (!response.ok) throw new Error('Preloaded demo manifest missing. Run the offline preparation script.');
  return validateDemoManifest(await response.json());
}

export function demoResult(target, scienceNote) {
  const observations = chronologicalFrames(target.observations.map(row => ({
    obs_id: row.obs_id, access_url: row.access_url, access_format: 'application/fits (preloaded cutout)',
    observed_at_utc: row.observed_at_utc, energy_bandpassname: `SPHEREx-D${row.detector}`,
    obs_collection: 'Preloaded IRSA SPHEREx', s_ra: null, s_dec: null, em_min: null, em_max: null, t_exptime: null,
    demo: row,
  }))).frames;
  return {mode: 'demo', status: target.status, ra: target.ra, dec: target.dec, count: observations.length, truncated: false, observations, science_note: scienceNote};
}

export async function loadDemoImage(observation, {signal, fetchImpl = fetch} = {}) {
  const row = observation.demo;
  if (!asset(row.metadata_path, row.image_id, 'metadata.json')) throw new Error('Invalid demo metadata path.');
  const response = await fetchImpl(row.metadata_path, {signal});
  if (!response.ok) throw new Error('Preloaded image metadata missing. Revalidate the demo bundle.');
  const bytes = await response.arrayBuffer();
  const actual = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(n => n.toString(16).padStart(2, '0')).join('');
  if (actual !== row.metadata_sha256) throw new Error('Preloaded metadata checksum mismatch. Revalidate the demo bundle.');
  const metadata = JSON.parse(new TextDecoder().decode(bytes));
  if (metadata.image_id !== row.image_id || metadata.observation_id !== row.obs_id || metadata.preview_url !== row.preview_path ||
      metadata.original_url !== row.fits_path || metadata.pixel_url !== `/api/demo/images/${row.image_id}/pixel` || metadata.demo !== true) {
    throw new Error('Preloaded image identity or asset paths differ from the manifest.');
  }
  return metadata;
}
