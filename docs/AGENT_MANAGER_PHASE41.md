# Phase 4.1
Registry and Supervisor expose snapshot and opt-in database audit. Set
AGENT_AUDIT_DB_READ=1 only with dedicated read-only credentials. PostgreSQL
repeatable-read read-only transaction, four-second statement timeout; SQLite
query_only for isolated testing. No production connection performed.
Each batch max 20 explicit symbols. Full market universe enumeration deferred.
Freshness heuristics: 30 days annual shared, 90 days other annual documents;
not a verified reporting calendar. Absent alternative sources do not reduce
freshness score; missing expected fields still reduce completeness.
Existing queue timestamps inform existing priority function. Source cooldown
uses cached next_attempt; lack of evidence is unknown. Independent provenance
verification, actual feed error classification and whole-market aggregation
remain deferred. No writes or automatic repair.
