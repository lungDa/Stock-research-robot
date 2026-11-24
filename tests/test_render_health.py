import json
from unittest.mock import Mock

import pytest

from scripts import check_render_health as health


class Response:
    def __init__(self, body=b'{"status":"ok"}', status=200):
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, limit):
        return self.body[:limit]


def test_empty_variable_uses_existing_backend():
    assert health.checked_url('  ') == health.DEFAULT_URL


@pytest.mark.parametrize('url', [
    'http://example.onrender.com/health',
    'https://example.com/health',
    'https://example.onrender.com.evil.test/health',
    'https://user:password@example.onrender.com/health',
    'https://example.onrender.com:8443/health',
    'https://example.onrender.com/ready',
    'https://example.onrender.com/health?token=secret',
    'https://example.onrender.com/health#fragment',
])
def test_rejects_urls_that_are_not_public_health_endpoints(url):
    with pytest.raises(ValueError):
        health.checked_url(url)


def test_health_checks_once_and_reports_elapsed_time(monkeypatch, capsys):
    request = Mock(return_value=Response())
    monkeypatch.setattr(health, 'urlopen', request)
    ticks = iter([10.0, 12.5])
    monkeypatch.setattr(health.time, 'monotonic', lambda: next(ticks))
    health.check(health.checked_url(''))
    assert request.call_count == 1
    assert request.call_args.args[0].full_url == health.DEFAULT_URL
    assert request.call_args.kwargs == {'timeout': 65}
    output = capsys.readouterr().out
    assert 'HTTP 200 and status=ok' in output
    assert '2.50s' in output and 'LINE delivery is not verified' in output


@pytest.mark.parametrize('response', [
    Response(b'<html>Waking up</html>'),
    Response(b'{"status":"starting"}'),
    Response(b'[]'),
    Response(status=503),
    Response(b'x' * (health.MAX_BYTES + 1)),
])
def test_loading_or_invalid_response_never_reports_success(monkeypatch, capsys, response):
    monkeypatch.setattr(health, 'urlopen', Mock(return_value=response))
    with pytest.raises((RuntimeError, json.JSONDecodeError)):
        health.check(health.DEFAULT_URL)
    assert 'Confirmed' not in capsys.readouterr().out


def test_timeout_propagates_without_unbounded_retries(monkeypatch):
    request = Mock(side_effect=TimeoutError('unavailable'))
    monkeypatch.setattr(health, 'urlopen', request)
    with pytest.raises(TimeoutError):
        health.check(health.DEFAULT_URL)
    assert request.call_count == 1


def test_readiness_requires_database_ok(monkeypatch):
    request = Mock(side_effect=[Response(b'{"status":"ok","database":"ok"}'), Response()])
    monkeypatch.setattr(health, 'urlopen', request)
    health.check(health.DEFAULT_URL, readiness=True)
    assert request.call_args.args[0].full_url.endswith('/ready')
    with pytest.raises(RuntimeError, match='database=ok'):
        health.check(health.DEFAULT_URL, readiness=True)
