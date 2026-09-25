"""Download API-returned file URLs without ever sending the API bearer token."""
import os
from pathlib import Path
from urllib.parse import urlsplit, urljoin
from urllib.request import Request, build_opener
from urllib.error import HTTPError, URLError
from .client import CanvasError, NoRedirect


def download(url, destination, max_bytes=100 * 1024 * 1024, transport=None):
    transport = transport or build_opener(NoRedirect()).open
    target = Path(destination)
    # Never infer output paths from untrusted server filenames.
    if max_bytes < 1:
        raise CanvasError('Download byte limit must be positive')
    for _ in range(6):
        u = urlsplit(url)
        if u.scheme != 'https' or not u.hostname or u.username or u.password:
            raise CanvasError('Refusing a non-HTTPS or credential-bearing download URL')
        try:
            response = transport(Request(url, headers={'User-Agent': 'canvas-pocket/0.1.0'}), timeout=30)
        except HTTPError as e:
            location = e.headers.get('Location')
            status = e.code
            e.close()
            if status in (301, 302, 303, 307, 308) and location:
                url = urljoin(url, location)
                continue
            raise CanvasError(f'Download HTTP {status}; refresh file metadata or check access.') from None
        except (URLError, OSError):
            raise CanvasError('Download connection failed; no signed URL was logged.') from None
        created = False
        try:
            with response:
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                created = True
                with os.fdopen(fd, 'wb') as out:
                    total = 0
                    while True:
                        chunk = response.read(min(65536, max_bytes - total + 1))
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            raise CanvasError('Download exceeds byte limit; partial file removed')
                        out.write(chunk)
            return {'saved': str(target), 'bytes': total}
        except Exception:
            if created:
                target.unlink(missing_ok=True)
            raise
    raise CanvasError('Too many download redirects')
