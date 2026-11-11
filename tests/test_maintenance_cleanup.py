"""Regression tests: cleanup must fail closed before touching persistent data."""
import pytest
from jobs import maintenance

def test_cleanup_blocks_when_maintenance_enabled(monkeypatch):
    calls=[]
    def blocked():
        calls.append('guard')
        raise SystemExit(75)
    monkeypatch.setattr(maintenance,'assert_writable',blocked)
    monkeypatch.setattr(maintenance,'init_db',lambda: calls.append('init'))
    with pytest.raises(SystemExit) as exc:
        maintenance.run()
    assert exc.value.code==75
    assert calls==['guard']

def test_cleanup_starts_with_guard_before_database_init(monkeypatch):
    calls=[]
    def guard():
        calls.append('guard')
        raise SystemExit(75)
    monkeypatch.setattr(maintenance,'assert_writable',guard)
    monkeypatch.setattr(maintenance,'init_db',lambda: calls.append('init'))
    with pytest.raises(SystemExit):
        maintenance.run()
    assert 'init' not in calls
