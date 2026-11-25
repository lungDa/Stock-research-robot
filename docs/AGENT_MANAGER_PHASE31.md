# Phase 3.1
New v2 checks are independently bounded (two workers, default 15s each).
Supervisor.monitor delegates to v2. The authenticated router is available for
explicit mounting in an isolated test app; production server is unchanged.
API origin is pinned to the Render service name in render.yaml; verify actual
origin before use. DB opt-in requires a dedicated read-only credential.
Calendar uses cached session data and 45-minute grace; no refresh/write.
Workflow evidence is per due window, not proof of report delivery. GitHub
public pagination is bounded to 100; missing evidence may reflect truncation.
Current subscriber preferences approximate historical expectations; missing
four-mode reports remain unknown because no eligible results may be valid.
Coverage is a provisional sample, never verified market completeness.
Live integration with real credentials remains unverified; tests are isolated.
