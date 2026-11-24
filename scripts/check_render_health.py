"""One bounded public health check, allowing time for a free instance to start."""
import argparse
import json
import os
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DEFAULT_URL = 'https://stock-research-robot.onrender.com/health'
MAX_BYTES = 16 * 1024


def checked_url(value):
    value = value.strip() or DEFAULT_URL
    parts = urlsplit(value)
    if (parts.scheme != 'https' or not parts.hostname
            or not parts.hostname.endswith('.onrender.com')
            or parts.username or parts.password or parts.port not in (None, 443)
            or parts.path != '/health' or parts.query or parts.fragment):
        raise ValueError('RENDER_HEALTH_URL must be an HTTPS onrender.com /health URL')
    return value


def check(url, *, readiness=False):
    if readiness:
        url = url.removesuffix('/health') + '/ready'
    started = time.monotonic()
    request = Request(url, headers={'Accept': 'application/json',
                                   'User-Agent': 'Stock-Lighthouse-Health-Check/1.0'})
    with urlopen(request, timeout=65) as response:
        if response.status != 200:
            raise RuntimeError('Render health did not return HTTP 200')
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise RuntimeError('Render health response exceeded 16 KiB budget')
    payload = json.loads(body)
    if not isinstance(payload, dict) or payload.get('status') != 'ok':
        raise RuntimeError('Render health JSON did not confirm status=ok')
    if readiness and payload.get('database') != 'ok':
        raise RuntimeError('Render readiness JSON did not confirm database=ok')
    endpoint = '/ready' if readiness else '/health'
    print(f'Confirmed Render {endpoint}: HTTP 200 and status=ok.')
    print(f'Render health response time: {time.monotonic()-started:.2f}s. LINE delivery is not verified by this check.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ready', action='store_true', help='Verify database connectivity')
    args = parser.parse_args()
    check(checked_url(os.getenv('RENDER_HEALTH_URL', '')), readiness=args.ready)

