from app.agents.contracts import Result, Task, Snapshot
from app.agents.permissions import allowed
from app.agents.registry import Registry

class Supervisor:
    """Disabled by default; no external tools, network, or persistence."""
    def __init__(self, *, enabled=False):
        self._enabled = enabled

    def run(self, task: Task, snapshot: Snapshot, *, is_admin=False) -> Result:
        if not allowed(task, enabled=self._enabled, is_admin=is_admin):
            return Result("unknown", "denied")
        agent = Registry().resolve(task.agent)
        if agent is None:
            return Result("unknown", "unknown_agent")
        try:
            if type(snapshot) is not Snapshot:
                raise ValueError("invalid snapshot")
            findings = agent.inspect(snapshot)
            return Result(task.agent, "attention" if findings else "ok", findings)
        except Exception:
            return Result(task.agent, "error")

    def monitor(self, *, is_admin=False, timeout=15):
        from app.agents.monitor_v2 import collect
        return collect(enabled=self._enabled, is_admin=is_admin, timeout=timeout)

    def audit_data(self, symbols, documents, *, now, is_admin=False):
        if self._enabled is not True or is_admin is not True:
            return {"mode":"shadow","status":"denied","rows":[]}
        return Registry().resolve("data_auditor").audit(symbols, documents, now=now)

    def audit_database(self, symbols, *, now, is_admin=False):
        if self._enabled is not True or is_admin is not True:
            return {"mode":"shadow","status":"denied","rows":[]}
        from app.agents.audit_reader import read_audit
        return read_audit(symbols, now=now)

    def audit_market(self, *, now, offset=0, expected_snapshot_at=None, is_admin=False):
        if self._enabled is not True or is_admin is not True:
            return {"mode":"shadow","status":"denied","rows":[]}
        from app.agents.audit_reader import read_market_page
        return read_market_page(now=now,offset=offset,expected_snapshot_at=expected_snapshot_at)

    def audit_market_snapshot(self, *, now, is_admin=False, timeout=30):
        if self._enabled is not True or is_admin is not True:
            return {"mode":"shadow","status":"denied"}
        from app.agents.audit_aggregate import read_market
        return read_market(now=now,timeout=timeout)

    def audit_notifications(self, *, now, read, users, days=7, is_admin=False):
        if self._enabled is not True or is_admin is not True:
            return {"mode":"shadow","status":"denied"}
        try:
            return Registry().resolve("notification").audit(now=now,read=read,users=users,days=days)
        except Exception:
            return {"mode":"shadow","status":"unknown"}

    def audit_notification_database(self, *, now, days=7, is_admin=False):
        if self._enabled is not True or is_admin is not True:
            return {"mode":"shadow","status":"denied"}
        from app.agents.notification_evidence import read_notifications
        return read_notifications(now=now,days=days)

    def audit_notification_isolated(self, *, now, days=7, timeout=35, is_admin=False):
        if self._enabled is not True or is_admin is not True:
            return {"mode":"shadow","status":"denied"}
        from app.agents.notification_process import collect
        return collect(now=now,days=days,timeout=timeout)
