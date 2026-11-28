"""Independent HTTP scheduler entry point; GitHub remains the fallback."""
import hmac
import logging
import os
import threading
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from app.services.freshness import local_now

router = APIRouter()
log = logging.getLogger(__name__)
_gate = threading.Lock()
DUE = {"morning": (11, 30), "watch": (18, 17), "evening": (19, 30)}

def execute(slot):
    try:
        from jobs.maintenance_guard import assert_writable
        assert_writable()
        if slot == "watch":
            from jobs.watch_digest import run
            result = run()
        else:
            from jobs.recommend import run
            result = run(slot, dry_run=False, catch_up=True)
        log.info("Scheduled LINE job slot=%s result=%s", slot, result)
    except (Exception, SystemExit) as exc:
        log.warning("Scheduled LINE job slot=%s failed=%s", slot, type(exc).__name__)
    finally:
        _gate.release()

@router.post("/internal/scheduled-reports/{slot}", status_code=202)
def trigger(slot: str, tasks: BackgroundTasks, authorization: str = Header(default="")):
    secret = os.getenv("REPORT_SCHEDULER_TOKEN", "")
    if len(secret) < 32:
        raise HTTPException(503, "Scheduler not configured")
    if not hmac.compare_digest(authorization.encode(), ("Bearer " + secret).encode()):
        raise HTTPException(401, "Unauthorized")
    if slot not in DUE:
        raise HTTPException(404, "Unknown slot")
    now = local_now()
    if now.weekday() >= 5 or (now.hour, now.minute) < DUE[slot]:
        return {"status": "outside_send_window", "slot": slot}
    if not _gate.acquire(blocking=False):
        return {"status": "busy", "slot": slot}
    tasks.add_task(execute, slot)
    return {"status": "queued", "slot": slot}
