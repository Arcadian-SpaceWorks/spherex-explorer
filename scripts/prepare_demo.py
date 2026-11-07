"""Reproducible OFFLINE preparation from existing FITS cutouts and source records.

.venv/bin/python scripts/prepare_demo.py --config demo/targets.json --output frontend/public/demo
.venv/bin/python scripts/prepare_demo.py --validate frontend/public/demo

Never downloads, edits inputs, or overwrites an existing output directory.
"""
import argparse
from importlib.metadata import version
import json
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.parse import urlsplit, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.demo import Manifest, digest, validate_bundle
from backend.app.fits_worker import process_fits
from backend.app.image_download import add_cutout_query, validate_cutout

SCIENCE_NOTE = ('Preloaded real SPHEREx cutouts, not a live archive query. PNGs are independently stretched display previews, not science data. '
                'Images differ in wavelength, coverage and detector orientation and are not spatially registered or photometrically matched. '
                'No source motion or brightness variation has been validated. Use the preserved FITS for scientific analysis.')


def prepare(config_path, output):
    config_path, output = Path(config_path).resolve(), Path(output).resolve()
    config = json.loads(config_path.read_text())
    if config.get('schema_version') != 1:
        raise ValueError('Unsupported preparation inventory version')
    if output.exists():
        raise ValueError('Output already exists; validate it or prepare a new directory instead')
    # Paths in the input inventory are relative to the configuration, never the shell cwd.
    targets = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.demo-prepare-', dir=output.parent) as temporary:
        staging = Path(temporary) / 'bundle'
        staging.mkdir()
        for item in config['targets']:
            target = {key: item[key] for key in ('id', 'name', 'ra', 'dec', 'coordinate_source')}
            target['science_context'] = item.get('science_context', '')
            target.update(status='missing', missing_reason=item.get('missing_reason', 'No verified local cutouts have been supplied for this target.'), observations=[])
            for source in item['inputs']:
                fits_path = (config_path.parent / source['fits']).resolve()
                record = json.loads((config_path.parent / source['metadata']).read_text())
                if not fits_path.is_file() or fits_path.stat().st_size > 128*1024*1024:
                    raise ValueError('Missing or oversized input FITS')
                sha = digest(fits_path)
                if sha != record.get('sha256'):
                    raise ValueError('Input FITS checksum differs from its source record')
                cutout = record.get('cutout') or {}
                validate_cutout(cutout.get('ra'), cutout.get('dec'), cutout.get('size_deg'))
                source_url = record['fits_url']
                parts = urlsplit(source_url)
                expected = add_cutout_query(parts._replace(query='').geturl(), cutout['ra'], cutout['dec'], cutout['size_deg'])
                if parse_qs(parts.query) != parse_qs(urlsplit(expected).query):
                    raise ValueError('Cutout URL does not match source record coordinates/size')
                import hashlib
                image_id = hashlib.sha256(f'{target["id"]}:{sha}'.encode()).hexdigest()
                directory = staging / 'assets' / image_id
                directory.mkdir(parents=True)
                original = directory / 'original.fits'
                shutil.copyfile(fits_path, original)
                from astropy.io import fits
                with fits.open(original, memmap=False) as hdul:
                    timesys = hdul['IMAGE'].header.get('TIMESYS', hdul[0].header.get('TIMESYS'))
                    if timesys != 'UTC':
                        raise ValueError('FITS must explicitly declare TIMESYS=UTC; no time-scale assumption is made')
                meta = process_fits('render', path=str(original), preview_path=str(directory / 'preview.png'), max_pixels=8_000_000)
                for key in ('observation_id', 'observed_at_utc', 'detector'):
                    if meta[key] is None or meta[key] != record.get(key):
                        raise ValueError(f'FITS {key} does not match recorded source metadata')
                # Both IBE URL and DataLink must identify this observation and detector.
                for url in (record['access_url'], source_url):
                    if meta['observation_id'] not in url or f'D{meta["detector"]}' not in url:
                        raise ValueError('Source URL identity differs from FITS observation/detector')
                frame_position = record.get('target_position', target)
                position = process_fits('target', path=str(original), ra=frame_position['ra'], dec=frame_position['dec'], max_pixels=8_000_000)
                if position['status'] != 'inside':
                    raise ValueError('Target is outside the cutout or lacks usable WCS')
                stamp = meta['observed_at_utc']
                if not stamp.endswith('Z'):
                    stamp += 'Z'
                prefix = f'/demo/assets/{image_id}'
                provenance = {'verification': 'FITS headers, local source record, SHA-256 and target WCS checked; origin not independently re-fetched',
                              'renderer': 'backend.app.fits_image.render_fits', 'renderer_sha256': digest(Path(__file__).resolve().parents[1] / 'backend/app/fits_image.py'),
                              'versions': {name: version(name) for name in ('astropy', 'numpy', 'Pillow')},
                              'registration': 'native detector; no spatial registration', 'normalization': 'independent 1–99 percentile asinh stretch; invalid pixels transparent',
                              'science_values': 'original FITS copied byte-for-byte', 'source_sha256': sha}
                meta.update(image_id=image_id, access_url=record['access_url'], fits_url=source_url, cutout=cutout,
                            sha256=sha, bytes=original.stat().st_size, demo=True, cache_hit=True, target=position,
                            provenance=provenance, preview_url=f'{prefix}/preview.png', original_url=f'{prefix}/original.fits',
                            pixel_url=f'/api/demo/images/{image_id}/pixel')
                acquisition = None
                if 'mission' in record:
                    from backend.app.demo import Acquisition
                    acquisition = Acquisition(**{key: record[key] for key in ('mission', 'data_release', 'calibration', 'position_source', 'position_mode', 'position_note', 'discovery_sha256', 'archive_em_min_m', 'archive_em_max_m')},
                                              ra=frame_position['ra'], dec=frame_position['dec']).model_dump()
                    meta['acquisition'] = acquisition
                (directory / 'metadata.json').write_text(json.dumps(meta, indent=2, sort_keys=True, allow_nan=False)+'\n')
                observation = dict(image_id=image_id, obs_id=meta['observation_id'], access_url=record['access_url'], source_url=source_url,
                                   observed_at_utc=stamp, detector=meta['detector'], spectral=meta['center']['spectral'],
                                   preview_path=meta['preview_url'], metadata_path=f'{prefix}/metadata.json', fits_path=meta['original_url'],
                                   fits_sha256=sha, preview_sha256=digest(directory / 'preview.png'), metadata_sha256=digest(directory / 'metadata.json'), provenance=provenance)
                if acquisition:
                    observation['acquisition'] = acquisition
                target['observations'].append(observation)
            if target['observations']:
                target.update(status='ready', missing_reason=None)
                target['observations'].sort(key=lambda o: (o['observed_at_utc'], o['obs_id'], o['detector']))
            targets.append(target)
        manifest = Manifest(schema_version=1, science_note=SCIENCE_NOTE, targets=targets)
        (staging / 'manifest.json').write_text(manifest.model_dump_json(indent=2)+'\n')
        validate_bundle(staging)
        staging.rename(output)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--validate', type=Path)
    args = parser.parse_args()
    if args.validate:
        manifest = validate_bundle(args.validate)
    else:
        if not args.config or not args.output:
            parser.error('--config and --output are required for preparation')
        manifest = prepare(args.config, args.output)
    for target in manifest.targets:
        print(f'{target.id}: {target.status}; {len(target.observations)} verified local cutouts')


if __name__ == '__main__':
    main()
