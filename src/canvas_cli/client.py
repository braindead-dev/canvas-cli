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


def valid_etag(value):
    """One bounded ASCII entity tag, never a wildcard/list or injected header."""
    return (isinstance(value, str) and len(value) <= 512 and
            re.fullmatch(r'(?:W/)?"[\x21\x23-\x7e]*"', value) is not None)


def _header(headers, name, *, combine=False):
    values = headers.get_all(name, []) if hasattr(headers, 'get_all') else [headers.get(name, '')]
    if not all(isinstance(value, str) for value in values):
        return None
    return ','.join(values) if combine else values[0] if len(values) == 1 else None


def _reusable(headers):
    control = _header(headers, 'Cache-Control', combine=True)
    vary = _header(headers, 'Vary', combine=True)
    if control is None or vary is None:
        return False
    control, vary = control.lower(), vary.lower()
    return ('no-store' not in control and
            all(field.strip() in ('', 'accept', 'accept-encoding', 'authorization')
                for field in vary.split(',')))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, host, token, transport=None):
        self.host = origin(host)
        self.token = token
        self.transport = transport or build_opener(NoRedirect()).open

    def request(self, route, method='GET', body=None, *, expect_no_content=False):
        url = self._request_url(route, method, expect_no_content)
        return self._send(url, method, body, expect_no_content=expect_no_content)

    def conditional_get(self, route, etag=None):
        """Revalidate one JSON resource; callers must bind their saved representation."""
        url = self._request_url(route, 'GET', False)
        if etag is not None and not valid_etag(etag):
            raise CanvasError('Invalid revalidation tag; no request was sent')
        return self._send(url, 'GET', None, conditional=True, etag=etag)

    def _request_url(self, route, method, expect_no_content):
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
        return url

    def graphql(self, document, variables, operation_name):
        """Fixed native endpoint; domain commands supply documents, never user query files."""
        if (not isinstance(document, str) or not document.strip() or
                not isinstance(variables, dict) or not isinstance(operation_name, str) or
                not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', operation_name)):
            raise CanvasError('Invalid GraphQL operation; no request was sent')
        body = {'query': document, 'variables': variables, 'operationName': operation_name}
        result, _ = self._send(self.host + '/api/graphql', 'POST', body, expected_status=200)
        if (not isinstance(result, dict) or result.get('errors') not in (None, []) or
                not isinstance(result.get('data'), dict)):
            raise CanvasError('Canvas returned GraphQL errors or incomplete data; no private response was logged. '
                              'An operation may have applied; check Canvas before repeating. No automatic retries.')
        return result['data']

    def _send(self, url, method, body, *, expect_no_content=False, expected_status=None,
              conditional=False, etag=None):
        try:
            payload = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8') if body is not None else None
        except (TypeError, ValueError, UnicodeError):
            raise CanvasError('Request body must be valid JSON; no request was sent or private content logged.') from None
        req = Request(url, method=method, headers={
            'Authorization': f'Bearer {self.token}', 'Accept': 'application/json',
            'Content-Type': 'application/json', 'User-Agent': 'canvas-cli/0.1.0'},
            data=payload)
        if conditional:
            req.add_header('Cache-Control', 'no-cache')
        if etag is not None:
            req.add_header('If-None-Match', etag)
        try:
            with self.transport(req, timeout=30) as response:
                if conditional:
                    return self._conditional_response(response, etag)
                if response.status == 304:
                    raise CanvasError('Unexpected revalidation response; no saved body was reused')
                if expected_status is not None and response.status != expected_status:
                    raise CanvasError('Canvas returned an unexpected GraphQL HTTP acknowledgement. '
                                      'Check Canvas before repeating an operation; no automatic retries.')
                if expect_no_content:
                    if response.status != 204 or response.read(1):
                        raise CanvasError('Canvas did not return the expected empty 204 acknowledgement. '
                                          'Verify the write in Canvas before repeating it; no automatic retries.')
                    return None, response.headers.get('Link', '')
                return load(response), response.headers.get('Link', '')
        except HTTPError as e:
            if conditional and e.code == 304:
                try:
                    with e:
                        return self._conditional_response(e, etag)
                except (TimeoutError, OSError):
                    raise CanvasError('Network failure during revalidation; no saved body was reused') from None
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

    @staticmethod
    def _conditional_response(response, supplied):
        tag = _header(response.headers, 'ETag')
        reusable = _reusable(response.headers)
        if response.status == 304:
            if supplied is None or tag != supplied or not reusable or response.read(1):
                raise CanvasError('Canvas returned an invalid revalidation acknowledgement; no saved body was reused')
            return {'not_modified': True, 'data': None, 'etag': tag}
        if response.status != 200:
            raise CanvasError('Canvas returned an unexpected revalidation response; no saved body was reused')
        try:
            data = load(response)
        except (ValueError, UnicodeError):
            raise CanvasError('Canvas returned an unexpected response; no response body was logged.') from None
        return {'not_modified': False, 'data': data,
                'etag': tag if reusable and valid_etag(tag) else None}

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
