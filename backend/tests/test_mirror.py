"""No network: S3-mirror ingestion, IRSA-identical local cutouts and non-blocking preparation.

Real data: the demo bundle's original.fits files are unmodified IRSA image-server cutouts.
Synthetic data (make_mef) is labelled where used.
"""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import hashlib
import json
from pathlib import Path
import shutil
import threading
import time
from urllib.parse import parse_qs, urlsplit

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from backend.app import pairs
from backend.app.fits_worker import process_fits
from backend.app.image_download import ImageError, MirrorDownloader, mirror_url, validate_mirror_url
from backend.app.image_service import ImageService
from backend.app.local_cutout import cutout_box, irsa_cutout
from backend.tests.test_images import ACCESS, FITS_URL, make_mef, settings  # noqa: F401 (fixture)

ROOT = Path(__file__).resolve().parents[2]
PRODUCT = ('https://irsa.ipac.caltech.edu/ibe/data/spherex/qr2/level2/2026W21_2A/l2b-v25-2026-147/5/'
           'level2_2026W21_2A_0213_2D5_spx_l2b-v25-2026-147.fits')
MIRROR = ('https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/qr2/level2/2026W21_2A/l2b-v25-2026-147/5/'
          'level2_2026W21_2A_0213_2D5_spx_l2b-v25-2026-147.fits')


def demo_cutouts():
    manifest = json.loads((ROOT / 'frontend/public/demo/manifest.json').read_text())
    for target in manifest['targets']:
        for row in target['observations']:
            query = parse_qs(urlsplit(row['source_url']).query)
            ra, dec = map(float, query['center'][0].split(','))
            yield ROOT / 'frontend/public' / row['fits_path'].lstrip('/'), ra, dec, float(query['size'][0].removesuffix('deg'))


def test_mirror_url_maps_only_plain_level2_products():
    assert mirror_url(PRODUCT) == MIRROR
    assert mirror_url(PRODUCT + '?center=1,2&size=0.3deg') is None
    assert mirror_url('https://irsa.ipac.caltech.edu/ibe/data/spherex/qr2/level1/x.fits') is None
    assert mirror_url('https://irsa.ipac.caltech.edu/data/SPHEREx/x.fits') is None


@pytest.mark.parametrize('url', [
    MIRROR.replace('https', 'http'), MIRROR + '?x=1', MIRROR.replace('nasa-irsa-spherex.', 'evil.'),
    MIRROR.replace('/qr2/level2/', '/qr2/level2/../'), MIRROR.replace('.s3.', '.s3.:8443.'),
    'https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/qr2/abs_gain_matrix/x.fits',
])
def test_mirror_allowlist_rejects_everything_else(url):
    with pytest.raises(ImageError) as error:
        validate_mirror_url(url)
    assert error.value.code == 'unsafe_url'


def test_cutting_an_irsa_cutout_again_reproduces_it_byte_for_byte(tmp_path):
    """REAL DATA: the box rule and header rewrite reproduce IRSA's own files exactly.

    Re-cutting an unclipped IRSA cutout with its own centre and size selects every pixel again, so the
    output must equal the input; clipped ones must keep exactly the rows/columns IRSA kept.
    """
    checked = 0
    for path, ra, dec, size in demo_cutouts():
        with fits.open(path) as hdul:
            box = cutout_box(hdul['IMAGE'].header, hdul, ra, dec, size)
            shape = hdul['IMAGE'].shape
            offset = (1 - hdul['IMAGE'].header['CRPIX1A'], 1 - hdul['IMAGE'].header['CRPIX2A'])
        if 0 < offset[0] and 0 < offset[1] and offset[0] + shape[1] < 2040 and offset[1] + shape[0] < 2040:
            assert box == (0, 0, shape[1], shape[0]), path.parent.name
            irsa_cutout(path, tmp_path / 'again.fits', ra, dec, size, 8_000_000)
            assert (tmp_path / 'again.fits').read_bytes() == path.read_bytes(), path.parent.name
            checked += 1
    assert checked >= 40


def test_worker_cutout_is_sandboxed_and_reports_the_box(tmp_path):
    """REAL DATA through the limited decoder process."""
    path, ra, dec, size = next(item for item in demo_cutouts() if item[3] == 0.437)
    box = process_fits('cutout', source=str(path), destination=str(tmp_path / 'small.fits'), ra=ra, dec=dec,
                       size_deg=0.2, max_pixels=8_000_000)
    with fits.open(path) as big, fits.open(tmp_path / 'small.fits') as small:
        assert [h.name for h in small] == [h.name for h in big]
        for name in ('IMAGE', 'FLAGS', 'VARIANCE', 'ZODI'):
            expected = big[name].data[box['y0']:box['y0'] + box['height'], box['x0']:box['x0'] + box['width']]
            assert np.array_equal(small[name].data, expected, equal_nan=True)
            assert small[name].header['CRPIX1W'] == big[name].header['CRPIX1W'] - box['x0']
        assert np.array_equal(small['PSF'].data, big['PSF'].data)
        assert small['WCS-WAVE'].data.tobytes() == big['WCS-WAVE'].data.tobytes()
        # The target keeps its sky position: same pixel, shifted by the box offset.
        w_big = WCS(big['IMAGE'].header, fobj=big, key=' ').celestial
        w_small = WCS(small['IMAGE'].header, fobj=small, key=' ').celestial
        xb, yb = w_big.all_world2pix([[ra, dec]], 0)[0]
        xs, ys = w_small.all_world2pix([[ra, dec]], 0)[0]
        assert (xb - box['x0'], yb - box['y0']) == pytest.approx((xs, ys), abs=1e-6)


def test_synthetic_clipping_and_outside_target(tmp_path):
    """TEST DATA: 6x8 synthetic product; a box at the corner is clipped, an outside target refused."""
    path = make_mef(tmp_path / 'synthetic.fits')
    with fits.open(path) as hdul:
        x, y = WCS(hdul['IMAGE'].header).all_world2pix([[210, 54]], 0)[0]
        assert (x, y) == pytest.approx((2, 3))
    box = irsa_cutout(path, tmp_path / 'corner.fits', 210, 54, 0.06, 1000)  # 6 px wanted, clipped at x=0
    assert box == {'x0': 0, 'y0': 0, 'width': 5, 'height': 6}
    with pytest.raises(ImageError) as error:
        irsa_cutout(path, tmp_path / 'outside.fits', 211, 54, 0.03, 1000)
    assert error.value.code == 'target_outside'


class FakeIRSA:
    """Stands in for IRSAImageDownloader: DataLink resolution, streaming and the IRSA fallback."""

    def __init__(self, product, length=None, fail_stream=False):
        self.product, self.length, self.fail_stream = product, length, fail_stream
        self.streams, self.fallbacks = [], []

    def resolve(self, session, access_url, deadline, *, cutout=False):
        return PRODUCT, self.length

    def _stream(self, session, url, sink, limit, deadline, *, validator, **kw):
        validator(url)
        self.streams.append(url)
        if self.fail_stream:
            raise ImageError('Synthetic mirror outage')
        sink.write(Path(self.product).read_bytes())
        return url

    def download(self, url, destination, cutout=None, progress=None):
        self.fallbacks.append((url, cutout))
        shutil.copyfile(self.product, destination)
        return url + ('?irsa-cutout' if cutout else '')


def cutter(calls):
    def cut(source, destination, ra, dec, size):
        calls.append((Path(source).name, ra, dec, size))
        shutil.copyfile(source, destination)
        return {'x0': 0, 'y0': 0, 'width': 8, 'height': 6}
    return cut


def test_mirror_download_is_reused_for_several_cutouts(settings, tmp_path):
    product = make_mef(tmp_path / 'synthetic.fits')
    irsa, calls = FakeIRSA(product, length=product.stat().st_size), []
    downloader = MirrorDownloader(settings, irsa=irsa, cutter=cutter(calls))
    url, delivery = downloader.fetch(ACCESS, tmp_path / 'a.fits', (210.0, 54.0, 0.3))
    assert url == PRODUCT + '?center=210.000000,54.000000&size=0.3000deg'  # Official equivalent cutout URL.
    assert delivery['source'] == 's3_mirror' and delivery['mirror_url'] == MIRROR
    downloader.fetch(ACCESS, tmp_path / 'b.fits', (210.0, 54.0, 0.437))
    full_url, full = downloader.fetch(ACCESS, tmp_path / 'full.fits')
    assert full_url == PRODUCT and full['cutout_box'] is None
    assert (tmp_path / 'full.fits').read_bytes() == product.read_bytes()
    assert irsa.streams == [MIRROR] and not irsa.fallbacks and len(calls) == 2


@pytest.mark.parametrize('problem', ['outage', 'size'])
def test_mirror_problems_fall_back_to_irsa(settings, tmp_path, problem):
    product = make_mef(tmp_path / 'synthetic.fits')
    irsa = FakeIRSA(product, length=product.stat().st_size + (1 if problem == 'size' else 0),
                    fail_stream=problem == 'outage')
    url, delivery = MirrorDownloader(settings, irsa=irsa, cutter=cutter([])).fetch(ACCESS, tmp_path / 'a.fits', (210.0, 54.0, 0.3))
    assert delivery['source'] == 'irsa' and irsa.fallbacks == [(PRODUCT, (210.0, 54.0, 0.3))]
    assert url == PRODUCT + '?irsa-cutout'
    assert not [p for p in downloader_sources(settings) if p.suffix == '.fits']


def downloader_sources(settings):
    folder = settings.cache_dir / '.sources'
    return list(folder.iterdir()) if folder.exists() else []


def test_outside_target_is_not_retried_at_irsa(settings, tmp_path):
    product = make_mef(tmp_path / 'synthetic.fits')
    irsa = FakeIRSA(product)
    def outside(*args):
        raise ImageError('The target is outside this detector image.', 422, 'target_outside')
    with pytest.raises(ImageError, match='outside'):
        MirrorDownloader(settings, irsa=irsa, cutter=outside).fetch(ACCESS, tmp_path / 'a.fits', (210.0, 54.0, 0.3))
    assert not irsa.fallbacks


def test_mirror_can_be_switched_off(settings, tmp_path):
    from dataclasses import replace
    product = make_mef(tmp_path / 'synthetic.fits')
    irsa = FakeIRSA(product)
    _, delivery = MirrorDownloader(replace(settings, mirror=False), irsa=irsa).fetch(ACCESS, tmp_path / 'a.fits')
    assert delivery['source'] == 'irsa' and not irsa.streams


def test_source_cache_is_bounded(settings, tmp_path):
    from dataclasses import replace
    product = make_mef(tmp_path / 'synthetic.fits')
    downloader = MirrorDownloader(replace(settings, source_cache_entries=2), irsa=FakeIRSA(product), cutter=cutter([]))
    for n in range(4):
        downloader._source(MIRROR.replace('2D5', f'2D{n}'), None, time.monotonic() + 60)
    assert len([p for p in downloader_sources(settings) if p.suffix == '.fits']) == 2


class SelectiveGate:
    """Downloader whose first observation is held until released; others finish at once."""

    def __init__(self, source, held):
        self.source, self.held = source, held
        self.entered, self.release = threading.Event(), threading.Event()

    def download(self, url, destination, cutout=None):
        if url == self.held:
            self.entered.set()
            assert self.release.wait(10)
        shutil.copyfile(self.source, destination)
        return FITS_URL


def test_a_slow_download_does_not_block_other_images(settings, tmp_path):
    downloader = SelectiveGate(make_mef(tmp_path / 'synthetic.fits'), held=ACCESS + '-slow')
    service = ImageService(settings, downloader)
    ready = service.prepare(ACCESS, 210, 54)
    with ThreadPoolExecutor(max_workers=2) as pool:
        slow = pool.submit(service.prepare, ACCESS + '-slow', 210, 54)
        assert downloader.entered.wait(5)
        try:
            # Before: every cache step waited for the slow download to finish.
            assert service.pixel(ready['image_id'], 2, 3)['value'] is not None
            assert service.prepare(ACCESS, 210, 54)['cache_hit'] is True
            assert service.prepare(ACCESS + '-other', 210, 54)['cache_hit'] is False
            with pytest.raises(TimeoutError):
                slow.result(timeout=0.1)
        finally:
            downloader.release.set()
        assert slow.result(timeout=10)['cache_hit'] is False


def test_cache_hit_reuses_the_stored_target_readout(settings, tmp_path, monkeypatch):
    service = ImageService(settings, SelectiveGate(make_mef(tmp_path / 'synthetic.fits'), held=None))
    first = service.prepare(ACCESS, 210, 54, 0.3)
    operations = []
    import backend.app.image_service as module
    original = module.process_fits
    monkeypatch.setattr(module, 'process_fits', lambda op, **kw: operations.append(op) or original(op, **kw))
    again = service.prepare(ACCESS, 210, 54, 0.3)
    assert again['cache_hit'] is True and again['target'] == first['target'] and operations == []
    moved = service.prepare(ACCESS, 210, 54.001, 0.3)
    assert moved['cache_hit'] is False and operations == ['render_target']
    assert 'stored_target' not in again and first['delivery'] == {'source': 'irsa'}


def test_pair_candidates_are_prepared_in_parallel_and_keep_their_order():
    rows = [{'obs_id': f'o{i}', 'access_url': f'u{i}', 't_min': 60000.0 + i * 30, 's_ra': 10.0, 's_dec': 41.0,
             'observed_at_utc': None, 'energy_bandpassname': 'SPHEREx-D1'} for i in range(6)]
    active, peak, lock = [0], [0], threading.Lock()

    class Service:
        def prepare(self, url, ra, dec, size):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.1)
            with lock:
                active[0] -= 1
            return {'image_id': url, 'preview_url': url, 'detector': 1, 'cache_hit': False,
                    'target': {'status': 'inside', 'spectral': {'wavelength_um': 0.9, 'bandwidth_um': 0.01}}}

    class Data:
        def observations(self, ra, dec, band):
            return {'observations': rows, 'source': 'test'}

    report = pairs.build_pair_report(Data(), Service(), 10.0, 41.0, per_visit=1)
    assert [c['obs_id'] for c in report['candidates']] == [r['obs_id'] for r in pairs.shortlist(rows, 10.0, 41.0, 1)]
    assert peak[0] == min(pairs.PARALLEL_FETCHES, len(report['candidates'])) > 1


def test_datalink_lookups_are_cached_and_size_limit_still_applies(settings, tmp_path):
    from dataclasses import replace
    product = make_mef(tmp_path / 'synthetic.fits')
    irsa = FakeIRSA(product, length=product.stat().st_size)
    lookups = []
    resolve = irsa.resolve
    irsa.resolve = lambda *a, **k: lookups.append(a[1]) or resolve(*a, **k)
    downloader = MirrorDownloader(settings, irsa=irsa, cutter=cutter([]))
    downloader.fetch(ACCESS, tmp_path / 'a.fits', (210.0, 54.0, 0.3))
    downloader.fetch(ACCESS, tmp_path / 'b.fits', (210.0, 54.0, 0.437))
    assert lookups == [ACCESS]
    small = MirrorDownloader(replace(settings, max_bytes=product.stat().st_size - 1), irsa=irsa, cutter=cutter([]))
    small.resolved = downloader.resolved
    with pytest.raises(ImageError) as error:
        small.fetch(ACCESS, tmp_path / 'full.fits')
    assert error.value.code == 'file_too_large'


def test_tile_compressed_flags_are_cut_into_a_plain_image(tmp_path):
    """TEST DATA: QR3 products store FLAGS tile-compressed; IRSA's cutout has a plain FLAGS image."""
    data = np.arange(400, dtype=np.float32).reshape(20, 20)
    flags = (np.arange(400, dtype=np.int32) * 7919 % 65536).reshape(20, 20)
    plain = make_mef(tmp_path / 'plain.fits', data=data, flags=flags)
    with fits.open(plain) as hdul:
        hdus = [h.copy() for h in hdul]
    index = next(i for i, h in enumerate(hdus) if h.name == 'FLAGS')
    hdus[index] = fits.CompImageHDU(data=flags, header=hdus[index].header, name='FLAGS', compression_type='RICE_1')
    fits.HDUList(hdus).writeto(tmp_path / 'compressed.fits')
    box_a = irsa_cutout(plain, tmp_path / 'a.fits', 210, 54, 0.05, 1000)
    box_b = irsa_cutout(tmp_path / 'compressed.fits', tmp_path / 'b.fits', 210, 54, 0.05, 1000)
    assert box_a == box_b
    # Header comments of a synthetic compressed HDU differ from the plain one; values must not.
    with fits.open(tmp_path / 'a.fits') as one, fits.open(tmp_path / 'b.fits') as cut:
        for x, y in zip(one, cut):
            assert dict(x.header) == dict(y.header) and x.name == y.name
            assert x.data is None or np.array_equal(x.data, y.data)
        assert type(cut['FLAGS']) is fits.ImageHDU
        assert np.array_equal(cut['FLAGS'].data, flags[box_a['y0']:box_a['y0'] + box_a['height'],
                                                         box_a['x0']:box_a['x0'] + box_a['width']])
