/**
 * Wavelength at the selected target, per observation, as measured from the image itself
 * (WCS-WAVE at the target pixel). IRSA search results only carry each product's whole
 * spectral range, so a value exists only after that observation's image has been prepared:
 * by the time slider, the inspector, a comparison or an explicit "Measure".
 *
 * Values are keyed by access URL and target position, because the wavelength at a target
 * depends on where that target falls on the detector.
 */
import { useSyncExternalStore } from 'react';

const values = new Map();
const listeners = new Set();
let version = 0;

export function wavelengthKey(row, target) {
  if (!row?.access_url || !target || !Number.isFinite(target.ra) || !Number.isFinite(target.dec)) return null;
  return `${row.access_url}|${target.ra.toFixed(6)}|${target.dec.toFixed(6)}`;
}

function emit() {
  version += 1;
  listeners.forEach(listener => listener());
}

/** status: 'measured' (with wavelength_um/bandwidth_um), 'outside' or 'unavailable'. */
export function recordTargetWavelength(row, target, info) {
  const key = wavelengthKey(row, target);
  if (!key) return;
  values.set(key, info);
  emit();
}

/** Record from a prepared image's metadata (POST /api/images or a demo metadata.json). */
export function recordFromMetadata(row, target, metadata) {
  const position = metadata?.target;
  if (!position) return;
  const spectral = position.spectral;
  if (position.status === 'inside' && Number.isFinite(spectral?.wavelength_um)) {
    recordTargetWavelength(row, target, {status: 'measured', wavelength_um: spectral.wavelength_um,
      bandwidth_um: Number.isFinite(spectral.bandwidth_um) ? spectral.bandwidth_um : null});
  } else {
    recordTargetWavelength(row, target, {status: position.status === 'outside' ? 'outside' : 'unavailable'});
  }
}

export function targetWavelength(row, target) {
  const key = wavelengthKey(row, target);
  return key ? values.get(key) || null : null;
}

export function clearTargetWavelengths() {
  values.clear();
  emit();
}

function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Re-render when any value changes; read values with targetWavelength(). */
export function useTargetWavelengthVersion() {
  return useSyncExternalStore(subscribe, () => version, () => version);
}
