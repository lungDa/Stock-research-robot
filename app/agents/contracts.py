from dataclasses import dataclass
from enum import Enum
from typing import Protocol

class Capability(str, Enum):
    READ_SNAPSHOT = "read_snapshot"
    WRITE = "write"
    SEND_LINE = "send_line"
    CALL_AI = "call_ai"
    TRADE = "trade"

@dataclass(frozen=True)
class Task:
    agent: str
    capability: Capability = Capability.READ_SNAPSHOT

@dataclass(frozen=True)
class Finding:
    code: str
    severity: str

@dataclass(frozen=True)
class Result:
    agent: str
    status: str
    findings: tuple[Finding, ...] = ()
    mode: str = "shadow"

@dataclass(frozen=True)
class Snapshot:
    database_ready: bool | None = None
    failed_jobs: int | None = None
    stale_jobs: int | None = None

    def __post_init__(self):
        if self.database_ready is not None and type(self.database_ready) is not bool:
            raise ValueError("invalid database status")
        for value in (self.failed_jobs, self.stale_jobs):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("invalid job count")

class Agent(Protocol):
    def inspect(self, snapshot: Snapshot) -> tuple[Finding, ...]: ...
