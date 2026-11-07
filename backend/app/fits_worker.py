"""Isolate native FITS/WCS decoding from the API process, with CPU/time limits."""
import contextlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys

from .image_download import ImageError

LOG = logging.getLogger(__name__)
# Safety limits for the decoder process. Some platforms (notably macOS for RLIMIT_AS) refuse
# some of them; the worker then still runs, and the missing limits are reported, never hidden.
LIMITS = (('RLIMIT_CORE', 0), ('RLIMIT_CPU', 55), ('RLIMIT_AS', 3 * 1024**3))
_reported = set()


def apply_limits(resource_module=None):
    """Apply each limit where the platform allows it; return the names that could not be applied."""
    if resource_module is None:
        import resource as resource_module
    missing = []
    for name, value in LIMITS:
        try:
            resource_module.setrlimit(getattr(resource_module, name), (value, value))
        except (AttributeError, ValueError, OSError):
            missing.append(name)
    return missing


def report_missing_limits(names):
    """Warn once per limit in the API log that the decoder runs without it."""
    new = [name for name in names if name not in _reported]
    if new:
        _reported.update(new)
        LOG.warning('FITS decoder is running WITHOUT these safety limits on this platform: %s', ', '.join(new))


def process_fits(operation, **arguments):
    try:
        result = subprocess.run([sys.executable, '-m', 'backend.app.fits_worker'],
                                input=json.dumps({'operation': operation, **arguments}),
                                text=True, capture_output=True, timeout=60,
                                cwd=Path(__file__).resolve().parents[2],
                                env={**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'})
        if result.returncode:
            raise ImageError('The FITS decoder could not safely read this product.', 422, 'invalid_fits')
        payload = json.loads(result.stdout)
        report_missing_limits(payload.get('limits_missing') or [])
        if 'error' in payload:
            error = payload['error']
            raise ImageError(error['message'], error['status'], error['code'])
        return payload['result']
    except subprocess.TimeoutExpired as exc:
        raise ImageError('FITS processing exceeded its time limit.', 504, 'processing_timeout') from exc
    except (ValueError, OSError) as exc:
        raise ImageError('The FITS decoder is unavailable.', 502, 'decoder_unavailable') from exc


def main():
    missing = apply_limits()  # No core dumps, CPU and memory caps for malformed native input.
    from .fits_image import read_pixel, render_fits, target_info
    arguments = json.load(sys.stdin)
    operation = arguments.pop('operation')
    try:
        with contextlib.redirect_stdout(sys.stderr):
            if operation == 'compare':
                # Imported only here: reproject/scipy are not needed for the other operations.
                from .analysis.pipeline import compare_files
                result = compare_files(**arguments)
            else:
                result = {'render': render_fits, 'target': target_info, 'pixel': read_pixel}[operation](**arguments)
        output = {'result': result}
    except ImageError as exc:
        output = {'error': {'message': str(exc), 'status': exc.status, 'code': exc.code}}
    except Exception:
        output = {'error': {'message': 'The FITS decoder could not interpret this product.', 'status': 422, 'code': 'invalid_fits'}}
    if missing:
        output['limits_missing'] = missing
    print(json.dumps(output, allow_nan=False))


if __name__ == '__main__':
    main()
