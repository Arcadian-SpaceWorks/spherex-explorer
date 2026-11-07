"""Bounded downloads of metadata-supplied SPHEREx products from IRSA only."""
from dataclasses import dataclass
from io import BytesIO
import ipaddress
import math
import os
from pathlib import Path
import socket
import time
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit, parse_qs

from astropy.io.votable import parse_single_table
import numpy as np
import requests


class ImageError(Exception):
    def __init__(self, message, status=502, code='image_unavailable'):
        super().__init__(message)
        self.status, self.code = status, code


@dataclass(frozen=True)
class ImageSettings:
    cache_dir: Path = Path(__file__).resolve().parents[2] / '.cache' / 'arcadian-fits-v1'
    max_bytes: int = 128 * 1024 * 1024
    cache_entries: int = 3
    cache_ttl: int = 3600
    max_pixels: int = 8_000_000
    download_seconds: int = 600

    @classmethod
    def from_env(cls):
        settings = cls(
            cache_dir=Path(os.getenv('SKYTRACKER_FITS_CACHE_DIR', str(cls.cache_dir))),
            max_bytes=int(os.getenv('SKYTRACKER_FITS_MAX_BYTES', 128 * 1024 * 1024)),
            cache_entries=int(os.getenv('SKYTRACKER_FITS_CACHE_ENTRIES', 3)),
            cache_ttl=int(os.getenv('SKYTRACKER_FITS_CACHE_TTL', 3600)),
            max_pixels=int(os.getenv('SKYTRACKER_FITS_MAX_PIXELS', 8_000_000)),
            download_seconds=int(os.getenv('SKYTRACKER_FITS_DOWNLOAD_SECONDS', 600)),
        )
        if min(settings.max_bytes, settings.cache_entries, settings.cache_ttl,
               settings.max_pixels, settings.download_seconds) <= 0:
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

    def _stream(self, session, url, sink, limit, deadline, *, cutout_query=None):
        for _ in range(5):
            validate_url(url)
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
                    total = 0
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if time.monotonic() > deadline:
                            raise ImageError('The IRSA download exceeded its time limit.', 504, 'download_timeout')
                        total += len(chunk)
                        if total > limit:
                            raise ImageError('The streamed file exceeds the configured download limit.', 413, 'file_too_large')
                        sink.write(chunk)
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

    def download(self, access_url, destination, cutout=None):
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
                    resolved_url = self._stream(session, fits_url, output, self.settings.max_bytes, deadline,
                                                cutout_query=urlsplit(fits_url).query if cutout is not None else None)
                with Path(destination).open('rb') as source:
                    if not source.read(80).startswith(b'SIMPLE  ='):
                        raise ImageError('The product is not an uncompressed FITS file.', 422, 'invalid_fits')
                return resolved_url
            except Exception:
                Path(destination).unlink(missing_ok=True)
                raise

    def resolve_datalink(self, payload, *, cutout=False):
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
                candidates.append(link)
            if len(set(candidates)) != 1:
                raise ImageError('DataLink did not provide one unambiguous original FITS product.')
            return candidates[0]
        except ImageError:
            raise
        except Exception as exc:
            raise ImageError('IRSA returned an unreadable DataLink table.') from exc
