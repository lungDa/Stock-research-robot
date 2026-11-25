# Phase 4.3
Single read-only transaction for market universe and all financial batches.
Aggregate rejects missing or duplicate symbols. Bounded 20-symbol queries,
cooperative deadline between batches, PostgreSQL statement timeout.
No external verification: distinct origins remain provisional, explicit
matching original filing IDs suppress distinct-origin conflict labels.
Seven-day age promotion for repair suggestions. SQLite DDL rejection test;
actual PostgreSQL rejection still requires isolated PostgreSQL validation.
No production access or automatic repair.

Reconciled equivalent functionality from 2c61074 without duplicate modules.
Explicit same-filing and unresolved-provenance conflict categories; IDs are
unverified metadata, never proof of independent filings. Added missing-symbol,
DML rejection, same-filing and starvation tests.
