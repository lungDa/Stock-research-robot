import pytest
from jobs import maintenance_guard

def test_guard_allows_normal_mode(monkeypatch):
    monkeypatch.setattr(maintenance_guard,'get',lambda key,default: {'enabled':False})
    maintenance_guard.assert_writable()

def test_guard_blocks_maintenance(monkeypatch):
    monkeypatch.setattr(maintenance_guard,'get',lambda key,default: {'enabled':True})
    with pytest.raises(SystemExit) as exc:
        maintenance_guard.assert_writable()
    assert exc.value.code==75

def test_guard_fails_closed_on_database_error(monkeypatch):
    def unavailable(*args):
        raise ConnectionError('database unavailable')
    monkeypatch.setattr(maintenance_guard,'get',unavailable)
    with pytest.raises(SystemExit) as exc:
        maintenance_guard.assert_writable()
    assert exc.value.code==75

def test_guard_rejects_malformed_state(monkeypatch):
    monkeypatch.setattr(maintenance_guard,'get',lambda key,default: 'bad state')
    with pytest.raises(SystemExit) as exc:
        maintenance_guard.assert_writable()
    assert exc.value.code==75
