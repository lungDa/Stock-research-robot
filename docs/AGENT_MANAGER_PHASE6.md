# Recovery Agent phase 6
Pure planner consumes supplied shadow reports; never invokes collectors, sender,
database, shell, AI or repair jobs. Stable IDs deduplicate category/scope, not
individual incidents. Retry and circuit states are advisory, supplied counters
are not persisted or trusted execution evidence. Root cause remains unconfirmed.
Approval is a requirement, not an approval workflow. Verification is simulation
only. Notification summaries cannot establish individual resend eligibility.
No production wiring. Future work: incident-specific identity, evidence
freshness, dependency correlation, richer notification policy integration,
durable approval/circuit state and independent verification in isolation.
