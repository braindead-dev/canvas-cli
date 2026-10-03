import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .strict_json import load


class CanvasError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def origin(value):
    u = urlsplit(value)
    if (u.scheme != 'https' or not u.hostname or u.username or u.password
            or u.path not in ('', '/') or u.query or u.fragment):
        raise CanvasError('Use an HTTPS Canvas origin, e.g. https://canvas.example.edu')
    return f'https://{u.netloc}'.rstrip('/')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, host, token, transport=None):
        self.host = origin(host)
        self.token = token
        self.transport = transport or build_opener(NoRedirect()).open

    def request(self, route, method='GET', body=None, *, expect_no_content=False):
        url = urljoin(self.host, route)
        u = urlsplit(url)
        decoded = unquote(u.path)
        parameters = parse_qs(u.query, keep_blank_values=True)
        if (f'{u.scheme}://{u.netloc}' != self.host or u.username or u.password
                or not u.path.startswith(('/api/v1/', '/api/quiz/v1/')) or u.fragment
                or any(p in ('.', '..') for p in decoded.split('/'))
                or '\\' in decoded
                or any(re.fullmatch(r'(access_token|as_user_id)(?:\[.*\])?', key.lower())
                       for key in parameters)):
            raise CanvasError('Refusing request outside the configured Canvas API origin')
        if method not in ('GET', 'POST', 'PUT', 'DELETE'):
            raise CanvasError('Unsupported method')
        if expect_no_content and method == 'GET':
            raise CanvasError('No-content acknowledgement is only supported for explicit writes')
        if method == 'GET' and any('read_status' in value
                for key, values in parameters.items() if re.fullmatch(r'include(?:\[.*\])?', key)
                for value in values):
            raise CanvasError('Refusing include[]=read_status because Canvas marks submissions read')
        canonical_path = re.sub(r'/+', '/', decoded).rstrip('/')
        if (method == 'GET' and re.fullmatch(r'/api/v1/conversations/\d+(?:\.json)?', canonical_path)
                and (parameters.get('auto_mark_as_read') != ['false'] or
                     any(key != 'auto_mark_as_read' and key.startswith('auto_mark_as_read[')
                         for key in parameters))):
            raise CanvasError('Conversation reads require auto_mark_as_read=false to avoid changing Inbox state')
        try:
            payload = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8') if body is not None else None
        except (TypeError, ValueError, UnicodeError):
            raise CanvasError('Request body must be valid JSON; no request was sent or private content logged.') from None
        req = Request(url, method=method, headers={
            'Authorization': f'Bearer {self.token}', 'Accept': 'application/json',
            'Content-Type': 'application/json', 'User-Agent': 'canvas-cli/0.1.0'},
            data=payload)
        try:
            with self.transport(req, timeout=30) as response:
                if expect_no_content:
                    if response.status != 204 or response.read(1):
                        raise CanvasError('Canvas did not return the expected empty 204 acknowledgement. '
                                          'Verify the write in Canvas before repeating it; no automatic retries.')
                    return None, response.headers.get('Link', '')
                return load(response), response.headers.get('Link', '')
        except HTTPError as e:
            e.close()
            if e.code == 401:
                raise CanvasError('Authentication expired or revoked. Run auth login again.', status=401) from None
            if e.code == 403:
                raise CanvasError('Canvas denied access. Check permissions/publication; this is not necessarily expired auth.', status=403) from None
            if e.code == 429:
                raise CanvasError('Canvas rate limit reached. Wait before retrying; no automatic write retries.', status=429) from None
            raise CanvasError(f'Canvas HTTP {e.code}. No automatic retries; verify a write in Canvas before repeating it.', status=e.code) from None
        except (URLError, TimeoutError, OSError):
            raise CanvasError('Network failure. If posting, verify in Canvas before retrying to avoid duplicates.') from None
        except (ValueError, UnicodeError):
            warning = ' The write may have applied; check Canvas before repeating. No automatic retries.' if method != 'GET' else ''
            raise CanvasError('Canvas returned an unexpected response; no response body was logged.' + warning) from None

    def list(self, route, max_pages=100):
        rows, seen = [], set()
        for _ in range(max_pages):
            if route in seen:
                raise CanvasError('Pagination loop detected')
            seen.add(route)
            data, links = self.request(route)
            if not isinstance(data, list):
                raise CanvasError('Expected a paginated list')
            rows.extend(data)
            match = re.search(r'<([^>]+)>;\s*rel="next"', links)
            if not match:
                return rows
            route = match.group(1)
        raise CanvasError('Page limit reached; increase --max-pages. Partial results were not emitted.')
