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
