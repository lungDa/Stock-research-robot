from app.agents.contracts import Capability, Task

def allowed(task: Task, *, enabled: bool, is_admin: bool) -> bool:
    return (enabled is True and is_admin is True
            and task.capability is Capability.READ_SNAPSHOT)
