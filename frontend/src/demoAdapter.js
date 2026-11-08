/** Local bundle adapter. No IRSA requests or synthetic fallback. */
import { chronologicalFrames, parseUtc } from './timeline.js';

const hash = /^[a-f0-9]{64}$/;
const asset = (value, id, name) => value === `/demo/assets/${id}/${name}`;
export function validateDemoManifest(data) {
  if (data?.schema_version !== 1 || typeof data.science_note !== 'string' || !Array.isArray(data.targets) || data.targets.length < 2 || data.targets.length > 8) {
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
      if (row.acquisition) {
        const a=row.acquisition;
        if (a.mission !== 'SPHEREx' || !['spherex_qr2','spherex_qr3'].includes(a.data_release) ||
            !source.pathname.includes(`/spherex/${a.data_release.slice(8)}/`) || !a.calibration || !source.pathname.split('/').includes(a.calibration) ||
            !Number.isFinite(a.ra) || a.ra < 0 || a.ra >= 360 || !Number.isFinite(a.dec) || Math.abs(a.dec)>90 ||
            !['moving-target-centered','fixed-sky-region'].includes(a.position_mode) || !a.position_source?.startsWith('https://') ||
            !hash.test(a.discovery_sha256) || !(a.archive_em_min_m>0) || !(a.archive_em_max_m>=a.archive_em_min_m) ||
            (a.predicted_ra == null) !== (a.predicted_dec == null) ||
            (a.predicted_ra != null && !(Number.isFinite(a.predicted_ra) && a.predicted_ra >= 0 && a.predicted_ra < 360 && Number.isFinite(a.predicted_dec) && Math.abs(a.predicted_dec) <= 90))) {
          throw new Error('Invalid demo acquisition provenance.');
        }
        const center=source.searchParams.get('center')?.split(',').map(Number);
        if (center?.length!==2 || Math.abs(center[0]-a.ra)>0.00000051 || Math.abs(center[1]-a.dec)>0.00000051) throw new Error('Cutout center differs from frame position.');
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
    obs_collection: row.acquisition?.data_release || 'Preloaded IRSA SPHEREx', s_ra: null, s_dec: null, em_min: row.acquisition?.archive_em_min_m ?? null, em_max: row.acquisition?.archive_em_max_m ?? null, t_exptime: null,
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
  if (row.acquisition && Object.entries(row.acquisition).some(([key,value])=>metadata.acquisition?.[key]!==value)) throw new Error('Preloaded acquisition provenance differs from manifest.');
  return metadata;
}

/** Data releases of a target's frames, in time order of first use (e.g. ['spherex_qr2', 'spherex_qr3']). */
export function targetReleases(target) {
  const rows = [...(target?.observations || [])].sort((a, b) => a.observed_at_utc.localeCompare(b.observed_at_utc));
  return [...new Set(rows.map(row => row.acquisition?.data_release).filter(Boolean))];
}

export function targetCoverage(target) {
  const rows = target?.observations || [];
  const times = [...new Set(rows.map(row => row.observed_at_utc))].sort();
  return {frames:rows.length, epochs:times.length, first:times[0], last:times.at(-1),
    days:times.length ? (Date.parse(times.at(-1))-Date.parse(times[0]))/86400000 : 0};
}
