# Agent Manager Phase 2

Opt-in, shadow-only prototype. No changes to existing entrypoints, schedules,
dependencies, database, LINE, AI providers or trading. The fixed registry
contains one deterministic System Monitor. It accepts only validated aggregate
snapshots supplied by trusted callers; it does not fetch production data.
Unknown evidence is not healthy. All capabilities except snapshot inspection
are denied. The admin boolean is a trusted internal assertion, not an
authentication mechanism; any future API must bind it to existing admin auth.
Results are returned in memory; persistent audit, live snapshot adapter,
dashboard and scheduling are deferred. Python modules are not a sandbox for
arbitrary untrusted code; do not add untrusted registry implementations.

Run `python -m pytest -q tests/test_agent_supervisor.py` or full
`python -m pytest -q` in isolated CI. No production deployment authorized.
