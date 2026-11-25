from app.agents.contracts import Finding, Snapshot

class SystemMonitor:
    """Pure inspection of caller-provided aggregate evidence."""
    def inspect(self, snapshot: Snapshot) -> tuple[Finding, ...]:
        findings = []
        if snapshot.database_ready is not True:
            findings.append(Finding("database_unknown" if snapshot.database_ready is None else "database_unready", "warning" if snapshot.database_ready is None else "critical"))
        for name, value in (("failed_jobs", snapshot.failed_jobs), ("stale_jobs", snapshot.stale_jobs)):
            if value is None:
                findings.append(Finding(name + "_unknown", "warning"))
            elif value > 0:
                findings.append(Finding(name, "warning"))
        return tuple(findings)
