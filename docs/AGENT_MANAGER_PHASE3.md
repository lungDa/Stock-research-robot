# Phase 3 shadow monitoring
Manual trusted-operator invocation only: call live_monitor.collect(enabled=True,
is_admin=True). No routes, schedules or production changes. The boolean is not
authentication. Each of three subprocesses has a 15-second default hard timeout
(max 30); HTTP operations have a 5-second timeout. Unknown is not healthy.
Configure AGENT_MONITOR_API_URL to the verified HTTPS stock API origin.
GitHub reads public main workflow metadata, not job logs; 96h freshness is a
conservative weekend-tolerant heuristic, not a trading calendar SLA.
Set AGENT_MONITOR_DB_READ=1 only with a dedicated read-only DB credential.
PostgreSQL transactions are read-only; no init_db or writes. Financial freshness
is based on the existing refresh job document, not full-market completeness.
Supply expected due outbox keys via AGENT_MONITOR_EXPECTED_OUTBOX_KEYS
(comma separated, max 20); caller determines trading day, due slot and subscribers.
Missing records are unknown, pending messages warning; ok means API acceptance
only, never handset delivery. No automatic subscriber discovery or resend.
Report contains fixed codes only. No raw exceptions, keys or response bodies.
CI uses mocked probes; live credentials and production validation are deferred.
