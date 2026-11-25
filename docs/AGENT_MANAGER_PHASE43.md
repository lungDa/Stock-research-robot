# Phase 4.3
Single read-only transaction for market universe and all financial batches.
Aggregate rejects missing or duplicate symbols. Bounded 20-symbol queries,
cooperative deadline between batches, PostgreSQL statement timeout.
No external verification: distinct origins remain provisional, explicit
matching original filing IDs suppress distinct-origin conflict labels.
Seven-day age promotion for repair suggestions. SQLite DDL rejection test;
actual PostgreSQL rejection still requires isolated PostgreSQL validation.
No production access or automatic repair.
