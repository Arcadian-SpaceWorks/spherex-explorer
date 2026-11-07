"""Isolate native FITS/WCS decoding from the API process, with CPU/time limits."""
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys

from .image_download import ImageError


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
        if 'error' in payload:
            error = payload['error']
            raise ImageError(error['message'], error['status'], error['code'])
        return payload['result']
    except subprocess.TimeoutExpired as exc:
        raise ImageError('FITS processing exceeded its time limit.', 504, 'processing_timeout') from exc
    except (ValueError, OSError) as exc:
        raise ImageError('The FITS decoder is unavailable.', 502, 'decoder_unavailable') from exc


def main():
    import resource  # Fedora/Linux deployment; no core dumps for malformed native input.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (55, 55))
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
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
    print(json.dumps(output, allow_nan=False))


if __name__ == '__main__':
    main()
