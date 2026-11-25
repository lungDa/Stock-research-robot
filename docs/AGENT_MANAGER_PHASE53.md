# Phase 5.3
Isolated version-1 snapshot contract: date, slot, report, complete, eligible_users.
Cron evidence requires original event schedule expression, never creation-time
inference. Version-1 error contract: http_status and reason. These contracts
have no production producer and are not proof of historical eligibility.
Recovery advice is conservative; no sender. Existing cached outboxes use
unknown eligibility. Job pagination is bounded to three pages per sampled run,
not exhaustive run history. Hard subprocess timeout is available via Supervisor;
legacy in-process method remains. Timeout test mocks subprocess exception,
not an actual hung child. No production wiring, writes or external calls in tests.
