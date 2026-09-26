import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


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

    def request(self, route, method='GET', body=None):
        url = urljoin(self.host, route)
        u = urlsplit(url)
        decoded = unquote(u.path)
        if (f'{u.scheme}://{u.netloc}' != self.host or u.username or u.password
                or not u.path.startswith(('/api/v1/', '/api/quiz/v1/')) or u.fragment
                or any(p in ('.', '..') for p in decoded.split('/'))
                or '\\' in decoded
                or any(k.lower() in ('access_token', 'as_user_id') for k in parse_qs(u.query))):
            raise CanvasError('Refusing request outside the configured Canvas API origin')
        if method not in ('GET', 'POST'):
            raise CanvasError('Unsupported method')
        parameters = parse_qs(u.query)
        if method == 'GET' and 'read_status' in parameters.get('include[]', []):
            raise CanvasError('Refusing include[]=read_status because Canvas marks submissions read')
        if (method == 'GET' and re.fullmatch(r'/api/v1/conversations/\d+', u.path)
                and parameters.get('auto_mark_as_read') != ['false']):
            raise CanvasError('Conversation reads require auto_mark_as_read=false to avoid changing Inbox state')
        req = Request(url, method=method, headers={
            'Authorization': f'Bearer {self.token}', 'Accept': 'application/json',
            'Content-Type': 'application/json', 'User-Agent': 'canvas-pocket/0.1.0'},
            data=json.dumps(body).encode() if body is not None else None)
        try:
            with self.transport(req, timeout=30) as response:
                return json.load(response), response.headers.get('Link', '')
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
            raise CanvasError('Canvas returned an unexpected response; no response body was logged.') from None

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
