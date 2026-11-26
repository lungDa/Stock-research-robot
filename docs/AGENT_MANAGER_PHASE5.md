# Notification Agent
Pure shadow analysis of supplied cached ranking outboxes, current subscribers
and existing trading calendar. No sender, database writes, scheduler changes,
or external requests. Seven-day default, fourteen-day maximum, 100 users.
Missing historical outboxes are provisional because historical subscription
snapshots and four-mode eligibility are not available. API acceptance is not
device delivery. Retry advice is manual only; never creates retry keys.
Other LINE notification types and live read-only collection remain future work.
