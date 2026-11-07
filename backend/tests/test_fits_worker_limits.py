"""FITS worker safety limits: applied where the platform allows, and never silently dropped."""
import json
import logging
from types import SimpleNamespace
from unittest.mock import patch

from backend.app import fits_worker
from backend.app.fits_worker import LIMITS, apply_limits, process_fits


class FakeResource:
    """Stands in for the resource module; refuses the limits named in `refuse` (as macOS does for RLIMIT_AS)."""
    def __init__(self, refuse=()):
        self.applied, self.refuse = [], set(refuse)
        for index, (name, _) in enumerate(LIMITS):
            setattr(self, name, index)

    def setrlimit(self, key, value):
        name = LIMITS[key][0]
        if name in self.refuse:
            raise ValueError('not allowed on this platform')
        self.applied.append((name, value))


def test_all_limits_applied_on_linux_like_platforms():
    fake = FakeResource()
    assert apply_limits(fake) == []
    assert fake.applied == [(name, (value, value)) for name, value in LIMITS]


def test_a_refused_limit_is_skipped_and_returned_while_the_others_still_apply():
    fake = FakeResource(refuse={'RLIMIT_AS'})
    assert apply_limits(fake) == ['RLIMIT_AS']
    assert [name for name, _ in fake.applied] == ['RLIMIT_CORE', 'RLIMIT_CPU']


def test_a_limit_missing_from_the_platform_is_reported():
    fake = FakeResource()
    del fake.RLIMIT_CORE
    assert apply_limits(fake) == ['RLIMIT_CORE']


def test_missing_limits_reach_the_api_log_once(caplog):
    fits_worker._reported.clear()
    payload = json.dumps({'result': {'ok': True}, 'limits_missing': ['RLIMIT_AS']})
    finished = SimpleNamespace(returncode=0, stdout=payload)
    with patch('backend.app.fits_worker.subprocess.run', return_value=finished), caplog.at_level(logging.WARNING):
        assert process_fits('pixel') == {'ok': True}
        assert process_fits('pixel') == {'ok': True}
    warnings = [record.getMessage() for record in caplog.records if 'WITHOUT' in record.getMessage()]
    assert warnings == ['FITS decoder is running WITHOUT these safety limits on this platform: RLIMIT_AS']
    fits_worker._reported.clear()


def test_the_real_worker_subprocess_reports_no_missing_limits_here(tmp_path, caplog):
    # Runs the actual decoder process (never apply_limits() in the test process itself, which would
    # cap the whole test run). On this Linux deployment every limit must apply.
    from test_images import make_mef
    fits_worker._reported.clear()
    with caplog.at_level(logging.WARNING):
        assert process_fits('pixel', path=str(make_mef(tmp_path / 'f.fits')), x=2, y=3, max_pixels=1000)['value'] == 26
    assert not [record for record in caplog.records if 'WITHOUT' in record.getMessage()]
