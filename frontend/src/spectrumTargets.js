// Positions whose spectra were measured with this app and agree with published results
// (see docs/spectral-fingerprint.md). `look` says what to look for; the app decides what it reports.
export const GUIDED_TARGETS = [
  {id: '3i-atlas', name: 'Comet 3I/ATLAS', moving: '3i-atlas', look: 'Interstellar comet: CO2 gas emission at 4.26 µm, and a large brightening from August to December 2025.'},
  {id: 'l1527', name: 'Protostar L1527', ra: 69.97458, dec: 26.05278, look: 'A star being born inside its cloud: water, CO2 and CO ice absorb its light.'},
  {id: 'ngc-1614', name: 'Starburst galaxy NGC 1614', ra: 68.5001, dec: -8.5791, look: 'A galaxy forming stars rapidly: the 3.3 µm emission of carbon molecules (PAHs).'},
  {id: 's5-0716', name: 'Blazar S5 0716+714', ra: 110.4727, dec: 71.34343, look: 'A jet from a black hole pointed at us: featureless spectrum that changes brightness between seasons.'},
  {id: 'pg-1634', name: 'Quasar PG 1634+706', ra: 248.62042, dec: 70.52583, look: 'Open the redshift ruler and set z = 1.337: hydrogen Hα lands on the bump at 1.53 µm.'},
];
