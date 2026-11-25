import pytest
from app.agents.contracts import Capability, Snapshot, Task
from app.agents.supervisor import Supervisor

def test_disabled_default():
    assert Supervisor().run(Task("system_monitor"), Snapshot(), is_admin=True).status == "denied"

def test_admin_required():
    assert Supervisor(enabled=True).run(Task("system_monitor"), Snapshot()).status == "denied"

@pytest.mark.parametrize("capability", [Capability.WRITE, Capability.SEND_LINE, Capability.CALL_AI, Capability.TRADE, "read_snapshot"])
def test_forbidden(capability):
    assert Supervisor(enabled=True).run(Task("system_monitor", capability), Snapshot(), is_admin=True).status == "denied"

def test_unknown_agent():
    assert Supervisor(enabled=True).run(Task("secret"), Snapshot(), is_admin=True).agent == "unknown"

def test_unknown_is_not_healthy():
    result = Supervisor(enabled=True).run(Task("system_monitor"), Snapshot(), is_admin=True)
    assert result.status == "attention"
    assert len(result.findings) == 3

def test_healthy():
    assert Supervisor(enabled=True).run(Task("system_monitor"), Snapshot(True, 0, 0), is_admin=True).status == "ok"

def test_failures():
    result = Supervisor(enabled=True).run(Task("system_monitor"), Snapshot(False, 2, 1), is_admin=True)
    assert {f.code for f in result.findings} == {"database_unready", "failed_jobs", "stale_jobs"}

@pytest.mark.parametrize("kwargs", [{"failed_jobs": -1}, {"stale_jobs": True}, {"database_ready": 1}])
def test_invalid_snapshot(kwargs):
    with pytest.raises(ValueError):
        Snapshot(**kwargs)

def test_invalid_input_is_sanitized():
    result = Supervisor(enabled=True).run(Task("system_monitor"), {"secret": "token"}, is_admin=True)
    assert result.status == "error"
    assert not result.findings
