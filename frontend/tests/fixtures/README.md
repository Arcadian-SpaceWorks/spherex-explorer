These are tiny synthetic test artifacts, never used by the application as fallback data.
`synthetic.fits` has an empty primary HDU, reordered IMAGE/FLAGS/VARIANCE HDUs,
a celestial WCS with an off-center target, and a 2×2 spectral WCS lookup grid.
The PNG and JSON were generated with the production FITS renderer. Fixture construction
is defined in `backend/tests/test_images.py` (`make_mef` and `add_spectral_table`).
