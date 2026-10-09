"""Request bounds, trusted proxy identities and persistent abuse limits."""
import hashlib
import ipaddress
import socket
import time
import math
from flask import current_app, request, abort
from flask.json.provider import DefaultJSONProvider
from database import central_db

JSON_LIMIT = 64 * 1024
INLINE_THEME = "document.getElementById('fgu-diary-design').dataset.theme=document.documentElement.dataset.fguTheme;"

class BoundedJSONProvider(DefaultJSONProvider):
    def loads(self, value, **kwargs):
        def invalid_constant(value):
            raise ValueError('Non-finite JSON number')
        kwargs['parse_constant'] = invalid_constant
        try:
            result = super().loads(value, **kwargs)
        except RecursionError:
            raise ValueError('JSON nesting limit') from None
        stack = [(result, 0)]
        while stack:
            item, depth = stack.pop()
            if depth > 32:raise ValueError('JSON nesting limit')
            if isinstance(item, dict):stack.extend((v, depth+1) for pair in item.items() for v in pair)
            elif isinstance(item, list):stack.extend((v, depth+1) for v in item)
            elif isinstance(item, str):
                try:item.encode('utf-8')
                except UnicodeEncodeError:raise ValueError('Invalid Unicode') from None
            elif type(item) is int and not -2**63 <= item < 2**63:raise ValueError('Integer outside supported range')
            elif type(item) is float and not math.isfinite(item):raise ValueError('Non-finite JSON number')
        return result


def configure(app):
    app.json = BoundedJSONProvider(app)
    proxies = set()
    # Only the named reverse proxy may supply a client address. Public callers
    # cannot gain new rate-limit buckets by inventing forwarding headers.
    for host in ('caddy', 'edge'):
        try:proxies.update(info[4][0] for info in socket.getaddrinfo(host, None))
        except socket.gaierror:pass
    app.config['TRUSTED_PROXY_IPS'] = proxies


def client_address():
    peer = request.remote_addr or 'unknown'
    forwarded = request.headers.get('X-Forwarded-For', '').split(',')[-1].strip()
    if peer in current_app.config.get('TRUSTED_PROXY_IPS', ()):
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return peer


def limit(bucket, identity, count, seconds, connection=None):
    key = hashlib.sha256((bucket + ':' + identity).encode()).hexdigest()
    now = int(time.time())
    def apply(c):
        c.execute('DELETE FROM web_attempts WHERE until<?', (now,))
        row = c.execute('SELECT count,until FROM web_attempts WHERE key=?', (key,)).fetchone()
        if row and row['count'] >= count:
            abort(429)
        c.execute('INSERT OR REPLACE INTO web_attempts VALUES(?,?,?)', (key, (row['count'] if row else 0) + 1, row['until'] if row else now + seconds))
    if connection is not None:apply(connection)
    else:
        with central_db() as c:
            c.execute('BEGIN IMMEDIATE');apply(c)


def bound_request():
    if request.path == '/api/files' and request.method == 'POST':
        request.max_content_length = 100 * 1024 * 1024
    elif request.path == '/api/schedule/import/preview':
        request.max_content_length = 16 * 1024 * 1024
    elif request.path == '/api/max/webhook':
        request.max_content_length = 128 * 1024
    elif request.path == '/api/schedule/import/commit':
        request.max_content_length = 1024 * 1024
    else:
        request.max_content_length = JSON_LIMIT
    if request.is_json:
        ceiling=1024*1024 if request.path=='/api/schedule/import/commit' else 128*1024 if request.path=='/api/max/webhook' else JSON_LIMIT
        request.max_content_length=min(request.max_content_length,ceiling)
    if request.content_length and request.content_length > request.max_content_length:
        abort(413)
    if request.is_json and not isinstance(request.get_json(),dict):abort(400)


def owner_limit(owner):
    path = request.path
    if path == '/api/account/export':
        limit('export', owner, 5, 900)
    elif path == '/api/schedule/import/preview':
        limit('recognition', owner, 8, 900)
    elif path == '/api/files' and request.method == 'POST':
        limit('upload', owner, 10, 900)
    elif request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        limit('write', owner, 180, 60)


def response_headers(response):
    import base64
    theme_hash = base64.b64encode(hashlib.sha256(INLINE_THEME.encode()).digest()).decode()
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self' 'wasm-unsafe-eval' https://st.max.ru 'sha256-" + theme_hash + "'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "font-src 'self' data:; worker-src 'self' blob:; connect-src 'self' https://st.max.ru; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; "
        "frame-ancestors 'self' https://web.telegram.org https://max.ru https://*.max.ru"
    )
    response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    if response.status_code == 429:
        response.headers['Retry-After'] = '60'
    return response
