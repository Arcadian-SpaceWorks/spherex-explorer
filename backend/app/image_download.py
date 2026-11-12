"""Bounded downloads of metadata-supplied SPHEREx products from IRSA only."""
from dataclasses import dataclass
import hashlib
from io import BytesIO
import ipaddress
import logging
import math
import os
from pathlib import Path
import re
import shutil
import socket
import tempfile
import threading
import time
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit, parse_qs

from astropy.io.votable import parse_single_table
import numpy as np
import requests

from .progress import NULL_PROGRESS

LOG = logging.getLogger(__name__)
# AWS Open Data mirror of the IRSA SPHEREx archive (anonymous HTTPS, same paths as /ibe/data/spherex/).
MIRROR_HOST = 'nasa-irsa-spherex.s3.us-east-1.amazonaws.com'
MIRROR_PATH = re.compile(r'^/qr\d+/level2/[A-Za-z0-9_.\-/]+\.fits$')

class ImageError(Exception):
    def __init__(self, message, status=502, code='image_unavailable'):
        super().__init__(message)
        self.status, self.code = status, code


@dataclass(frozen=True)
class ImageSettings:
    cache_dir: Path = Path(__file__).resolve().parents[2] / '.cache' / 'arcadian-fits-v1'
    max_bytes: int = 128 * 1024 * 1024
    cache_entries: int = 3
    cache_ttl: int = 21600
    max_pixels: int = 8_000_000
    download_seconds: int = 600
    cutout_cache_entries: int = 48
    # Full products from the S3 mirror kept for further cutouts (about 72 MB each).
    mirror: bool = True
    source_cache_entries: int = 4

    @classmethod
    def from_env(cls):
        settings = cls(
            cache_dir=Path(os.getenv('SKYTRACKER_FITS_CACHE_DIR', str(cls.cache_dir))),
            max_bytes=int(os.getenv('SKYTRACKER_FITS_MAX_BYTES', 128 * 1024 * 1024)),
            cache_entries=int(os.getenv('SKYTRACKER_FITS_CACHE_ENTRIES', 3)),
            cache_ttl=int(os.getenv('SKYTRACKER_FITS_CACHE_TTL', cls.cache_ttl)),
            max_pixels=int(os.getenv('SKYTRACKER_FITS_MAX_PIXELS', 8_000_000)),
            download_seconds=int(os.getenv('SKYTRACKER_FITS_DOWNLOAD_SECONDS', 600)),
            cutout_cache_entries=int(os.getenv('SKYTRACKER_CUTOUT_CACHE_ENTRIES', cls.cutout_cache_entries)),
            mirror=os.getenv('SKYTRACKER_S3_MIRROR', '1').strip().lower() not in ('0', 'false', 'no', 'off'),
            source_cache_entries=int(os.getenv('SKYTRACKER_SOURCE_CACHE_ENTRIES', cls.source_cache_entries)),
        )
        if min(settings.max_bytes, settings.cache_entries, settings.cache_ttl, settings.max_pixels,
               settings.download_seconds, settings.cutout_cache_entries, settings.source_cache_entries) <= 0:
            raise ValueError('FITS limits must be positive integers')
        return settings


def validate_url(url):
    """Exact host/path allowlist: no credentials, IP literals, ports or proxy endpoints."""
    try:
        if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 33 for c in url) or '\\' in url:
            raise ValueError()
        parts = urlsplit(url)
        if (parts.scheme != 'https' or parts.hostname != 'irsa.ipac.caltech.edu'
                or parts.username is not None or parts.password is not None
                or parts.port not in (None, 443) or parts.fragment):
            raise ValueError()
        path = unquote(parts.path)
        if '%' in path or '\\' in path or any(ord(c) < 32 for c in path) or any(part in ('.', '..') for part in path.split('/')):
            raise ValueError()
        if not (path == '/datalink/links/spherex' or path.startswith('/ibe/data/spherex/')
                or path.startswith('/data/SPHEREx/')):
            raise ValueError()
    except (ValueError, TypeError):
        raise ImageError('Only HTTPS SPHEREx product URLs on irsa.ipac.caltech.edu are allowed.', 400, 'unsafe_url')
    return url


def mirror_url(fits_url):
    """S3 mirror URL of a plain IRSA level-2 product URL, or None when there is no mirror path."""
    validate_url(fits_url)
    parts = urlsplit(fits_url)
    path = unquote(parts.path)
    if parts.query or not path.startswith('/ibe/data/spherex/'):
        return None
    key = path.removeprefix('/ibe/data/spherex')
    if not MIRROR_PATH.fullmatch(key):
        return None
    return validate_mirror_url(f'https://{MIRROR_HOST}{key}')


def validate_mirror_url(url):
    """Exact allowlist for the S3 mirror: HTTPS, one host, level-2 FITS paths, nothing else."""
    try:
        parts = urlsplit(url)
        path = unquote(parts.path)
        if (parts.scheme != 'https' or parts.hostname != MIRROR_HOST or parts.username is not None
                or parts.password is not None or parts.port not in (None, 443) or parts.query or parts.fragment
                or '%' in path or any(part in ('.', '..') for part in path.split('/')) or not MIRROR_PATH.fullmatch(path)):
            raise ValueError()
    except (ValueError, TypeError):
        raise ImageError('Only SPHEREx level-2 products on the IRSA S3 mirror are allowed.', 400, 'unsafe_url')
    return url


def validate_cutout(ra, dec, size_deg):
    values = (ra, dec, size_deg)
    if (not all(type(v) in (int, float) and math.isfinite(v) for v in values)
            or not 0 <= ra < 360 or not -90 <= dec <= 90 or not 0.02 <= size_deg <= 1):
        raise ImageError('Invalid cutout parameters.', 400, 'invalid_cutout')


def add_cutout_query(url, ra, dec, size_deg):
    """IRSA image-server cutout: append center/size to a SPHEREx product URL.

    This is the cutout method in IRSA's SPHEREx data-access documentation. Only validated
    finite numbers are formatted into the query, and the result is re-validated.
    """
    validate_url(url)
    parts = urlsplit(url)
    if parts.query or not unquote(parts.path).startswith('/ibe/data/spherex/'):
        raise ImageError('Cutouts are only available for IRSA SPHEREx image-server products.', 422, 'cutout_unsupported')
    validate_cutout(ra, dec, size_deg)
    query = f'center={ra:.6f},{dec:.6f}&size={size_deg:.4f}deg'
    return validate_url(urlunsplit(parts._replace(query=query)))


def check_public_dns(url):
    try:
        addresses = socket.getaddrinfo(urlsplit(url).hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ImageError('IRSA resolved to a non-public address; download blocked.', 400, 'unsafe_url')
    except OSError as exc:
        raise ImageError('Could not resolve IRSA. Please retry.') from exc


class IRSAImageDownloader:
    def __init__(self, settings):
        self.settings = settings

    def _stream(self, session, url, sink, limit, deadline, *, cutout_query=None, validator=validate_url, progress=None):
        for _ in range(5):
            validator(url)
            if cutout_query is not None and (
                    not unquote(urlsplit(url).path).startswith('/ibe/data/spherex/')
                    or parse_qs(urlsplit(url).query) != parse_qs(cutout_query)):
                raise ImageError('IRSA redirected away from the requested cutout; full-file fallback blocked.',
                                 502, 'cutout_unsupported')
            check_public_dns(url)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ImageError('The IRSA download exceeded its time limit.', 504, 'download_timeout')
            try:
                with session.get(url, stream=True, allow_redirects=False,
                                 timeout=(min(10, remaining), min(30, remaining)),
                                 headers={'Accept-Encoding': 'identity'}) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get('Location')
                        if not location:
                            raise ImageError('IRSA sent a redirect without a destination.')
                        url = urljoin(url, location)
                        continue  # Every new destination is revalidated before connection.
                    response.raise_for_status()
                    if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                        raise ImageError('Unexpected compressed HTTP response from IRSA.')
                    length = response.headers.get('Content-Length')
                    try:
                        if length is not None and int(length) > limit:
                            raise ImageError(f'The remote file exceeds the {limit // (1024 * 1024)} MiB download limit.', 413, 'file_too_large')
                    except ValueError as exc:
                        raise ImageError('Invalid download length returned by IRSA.') from exc
                    expected = int(length) if length is not None else None  # IRSA cutouts do not state one.
                    total = 0
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if time.monotonic() > deadline:
                            raise ImageError('The IRSA download exceeded its time limit.', 504, 'download_timeout')
                        total += len(chunk)
                        if total > limit:
                            raise ImageError('The streamed file exceeds the configured download limit.', 413, 'file_too_large')
                        sink.write(chunk)
                        if progress is not None:
                            progress(total, expected)
                    if not total:
                        raise ImageError('IRSA returned an empty file.')
                    if length is not None and total != int(length):
                        raise ImageError('The IRSA download was incomplete. Please retry.')
                    return url
            except requests.Timeout as exc:
                raise ImageError('IRSA timed out while downloading the image. Please retry.', 504, 'download_timeout') from exc
            except requests.RequestException as exc:
                raise ImageError('IRSA could not deliver this image. Please retry.') from exc
        raise ImageError('Too many IRSA redirects.')

    def download(self, access_url, destination, cutout=None, progress=None):
        """cutout=(ra, dec, size_deg) requests a small IRSA cutout instead of the full file."""
        validate_url(access_url)
        if cutout is not None:
            # Validate before making even a metadata request.
            validate_cutout(*cutout)
        deadline = time.monotonic() + self.settings.download_seconds
        # Disable environment proxies and .netrc credentials for this public-data client.
        with requests.Session() as session:
            session.trust_env = False
            fits_url = access_url
            if urlsplit(access_url).path == '/datalink/links/spherex':
                payload = BytesIO()
                self._stream(session, access_url, payload, 2 * 1024 * 1024, deadline)
                fits_url = self.resolve_datalink(payload.getvalue(), cutout=cutout is not None)
            if cutout is not None:
                fits_url = add_cutout_query(fits_url, *cutout)
            try:
                with Path(destination).open('wb') as output:
                    resolved_url = self._stream(session, fits_url, output, self.settings.max_bytes, deadline, progress=progress,
                                                cutout_query=urlsplit(fits_url).query if cutout is not None else None)
                with Path(destination).open('rb') as source:
                    if not source.read(80).startswith(b'SIMPLE  ='):
                        raise ImageError('The product is not an uncompressed FITS file.', 422, 'invalid_fits')
                return resolved_url
            except Exception:
                Path(destination).unlink(missing_ok=True)
                raise

    def resolve_datalink(self, payload, *, cutout=False):
        return self.datalink_product(payload, cutout=cutout)[0]

    def resolve(self, session, access_url, deadline, *, cutout=False):
        """(plain product URL, IRSA-reported byte length or None) for a DataLink or product URL."""
        validate_url(access_url)
        if urlsplit(access_url).path != '/datalink/links/spherex':
            return access_url, None
        payload = BytesIO()
        self._stream(session, access_url, payload, 2 * 1024 * 1024, deadline)
        return self.datalink_product(payload.getvalue(), cutout=cutout)

    def datalink_product(self, payload, *, cutout=False):
        try:
            table = parse_single_table(BytesIO(payload)).to_table(use_names_over_ids=True)
            required = {'semantics', 'access_url', 'content_type'}
            if not required.issubset(table.colnames):
                raise ValueError('Missing DataLink columns')
            candidates = []
            for row in table:
                def value(name):
                    if name not in table.colnames or np.ma.is_masked(row[name]):
                        return ''
                    item = row[name]
                    return item.decode() if isinstance(item, bytes) else str(item).strip()
                if value('semantics') not in ('#this', 'http://www.ivoa.net/rdf/datalink/core#this', 'https://www.ivoa.net/rdf/datalink/core#this'):
                    continue
                if value('error_message'):
                    raise ImageError('IRSA DataLink reports that the original product is unavailable.')
                if value('content_type').split(';')[0].lower() not in ('image/fits', 'application/fits'):
                    continue
                link = value('access_url')
                if not link:
                    continue
                validate_url(link)
                length = value('content_length')
                if not cutout and length and int(length) > self.settings.max_bytes:
                    raise ImageError('This FITS product exceeds the configured maximum download size.', 413, 'file_too_large')
                candidates.append((link, int(length) if length else None))
            if len({link for link, _ in candidates}) != 1:
                raise ImageError('DataLink did not provide one unambiguous original FITS product.')
            return candidates[0]
        except ImageError:
            raise
        except Exception as exc:
            raise ImageError('IRSA returned an unreadable DataLink table.') from exc


class MirrorDownloader:
    """Full products from the S3 mirror plus local IRSA-identical cutouts; IRSA itself as fallback.

    From this deployment IRSA delivers roughly 0.3 MB/s (a 0.3 deg cutout takes about 20 s), while
    the mirror delivers a whole 72 MB product in about 5 s. The full product is kept briefly, so a
    viewer cutout, a comparison cutout and pair suggestions of the same exposure share one download.
    """

    def __init__(self, settings, irsa=None, cutter=None):
        self.settings = settings
        self.irsa = irsa or IRSAImageDownloader(settings)
        self.cutter = cutter  # cutter(source, destination, ra, dec, size_deg) -> box; default: sandboxed worker
        self.lock = threading.Lock()
        self.keys = {}
        self.resolved = {}  # access_url -> (time, product URL, length): DataLink costs 1-2 s per call.

    @property
    def source_dir(self):
        return self.settings.cache_dir / '.sources'

    def download(self, access_url, destination, cutout=None):
        return self.fetch(access_url, destination, cutout)[0]

    def fetch(self, access_url, destination, cutout=None, progress=NULL_PROGRESS):
        """(official product/cutout URL, delivery record). Same contract as IRSAImageDownloader.download."""
        validate_url(access_url)
        if cutout is not None:
            validate_cutout(*cutout)
        deadline = time.monotonic() + self.settings.download_seconds
        progress.stage('locating', source='IRSA')
        fits_url, length = self._resolve(access_url, deadline, cutout is not None)
        official = add_cutout_query(fits_url, *cutout) if cutout is not None else fits_url
        source_url = mirror_url(fits_url) if self.settings.mirror else None
        if source_url:
            try:
                source = self._source(source_url, length, deadline, progress)
                if cutout is None:
                    shutil.copyfile(source, destination)
                    box = None
                else:
                    progress.stage('cutting')
                    box = self._cut(source, destination, *cutout)
                return official, {'source': 's3_mirror', 'mirror_url': source_url, 'cutout_box': box,
                                  'method': ('IRSA-identical local cutout of the mirrored product' if cutout is not None
                                             else 'mirrored product, byte length checked against IRSA DataLink'
                                             if length else 'mirrored product')}
            except ImageError as exc:
                if exc.code in ('target_outside', 'image_too_large'):
                    raise  # IRSA would fail the same way; do not wait for it.
                LOG.warning('S3 mirror unavailable for %s (%s); falling back to IRSA.', source_url, exc)
            except Exception as exc:  # Any mirror problem: the official service still works.
                LOG.warning('S3 mirror failed for %s (%s); falling back to IRSA.', source_url, exc)
            Path(destination).unlink(missing_ok=True)
        progress.stage('downloading', source='IRSA')
        resolved = self.irsa.download(fits_url, destination, cutout=cutout, progress=progress.received)
        return resolved, {'source': 'irsa', 'mirror_url': None, 'cutout_box': None,
                          'method': 'IRSA image-server cutout' if cutout is not None else 'IRSA product download'}

    def _resolve(self, access_url, deadline, cutout):
        with self.lock:
            cached = self.resolved.get(access_url)
        if cached and time.monotonic() - cached[0] < self.settings.cache_ttl:
            fits_url, length = cached[1], cached[2]
        else:
            with requests.Session() as session:
                session.trust_env = False
                fits_url, length = self.irsa.resolve(session, access_url, deadline, cutout=True)
            with self.lock:
                if len(self.resolved) >= 512:
                    self.resolved.pop(next(iter(self.resolved)))
                self.resolved[access_url] = (time.monotonic(), fits_url, length)
        if not cutout and length and length > self.settings.max_bytes:
            raise ImageError('This FITS product exceeds the configured maximum download size.', 413, 'file_too_large')
        return fits_url, length

    def _cut(self, source, destination, ra, dec, size_deg):
        if self.cutter is not None:
            return self.cutter(source, destination, ra, dec, size_deg)
        from .fits_worker import process_fits
        return process_fits('cutout', source=str(Path(source).resolve()), destination=str(Path(destination).resolve()),
                            ra=ra, dec=dec, size_deg=size_deg, max_pixels=self.settings.max_pixels)

    def _key_lock(self, name):
        with self.lock:
            return self.keys.setdefault(name, threading.Lock())

    def _source(self, url, expected_length, deadline, progress=NULL_PROGRESS):
        """Local path of the mirrored full product, downloading it once (per process) if needed."""
        name = hashlib.sha256(url.encode()).hexdigest() + '.fits'
        with self._key_lock(name):
            self.source_dir.mkdir(parents=True, exist_ok=True)
            path = self.source_dir / name
            if path.is_file() and not path.is_symlink() and (expected_length is None or path.stat().st_size == expected_length):
                path.touch()
                return path
            self._prune(reserve=1)
            progress.stage('downloading', source='AWS mirror')
            handle, temporary = tempfile.mkstemp(prefix='.part-', suffix='.fits', dir=self.source_dir)
            os.close(handle)
            try:
                with requests.Session() as session, open(temporary, 'wb') as sink:
                    session.trust_env = False
                    self.irsa._stream(session, url, sink, self.settings.max_bytes, deadline, validator=validate_mirror_url,
                                      progress=progress.received)
                size = os.path.getsize(temporary)
                if expected_length is not None and size != expected_length:
                    raise ImageError('The mirrored product differs in size from the IRSA original.', 502, 'mirror_mismatch')
                with open(temporary, 'rb') as check:
                    if not check.read(80).startswith(b'SIMPLE  ='):
                        raise ImageError('The mirrored product is not an uncompressed FITS file.', 502, 'mirror_mismatch')
                os.replace(temporary, path)
                return path
            finally:
                Path(temporary).unlink(missing_ok=True)

    def _prune(self, reserve=0):
        now = time.time()
        entries = []
        for path in self.source_dir.iterdir():
            try:
                age = now - path.stat().st_mtime
                if path.name.startswith('.part-'):
                    if age > self.settings.download_seconds:
                        path.unlink(missing_ok=True)
                elif path.suffix == '.fits' and not path.is_symlink():
                    if age > self.settings.cache_ttl:
                        path.unlink(missing_ok=True)
                    else:
                        entries.append(path)
            except OSError:
                continue
        entries.sort(key=lambda path: path.stat().st_mtime)
        for path in entries[:max(0, len(entries) - self.settings.source_cache_entries + reserve)]:
            path.unlink(missing_ok=True)  # Open handles (another cutout in progress) stay valid on POSIX.
