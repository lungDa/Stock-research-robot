"""Read-only schedule and evidence policy. All times are Taipei local."""
from datetime import timedelta
from app.services.trading_calendar import session

def due_slots(now, read, times, trading=True, grace=45):
    for offset in range(40):
        day = now.date() - timedelta(days=offset)
        candidates = [now.replace(year=day.year, month=day.month, day=day.day, hour=h, minute=m, second=0, microsecond=0) for h,m in times]
        candidates = [t for t in candidates if t + timedelta(minutes=grace) <= now]
        if not candidates:
            continue
        if trading:
            state = session(day, read)
            if state is None:
                return None
            if not state:
                continue
        return candidates
    return None

def coverage(doc, now):
    if not isinstance(doc, dict):
        return "unknown", None
    n, d, at = (doc.get(k) for k in ("known_items", "expected_items", "at"))
    if type(n) is not int or type(d) is not int or not 0 <= n <= d or d == 0:
        return "unknown", None
    if type(at) not in (int,float) or not 0 <= now.timestamp()-at <= 8*3600:
        return "unknown", None
    pct = round(100*n/d, 2)
    return ("warning" if n < d else "unknown"), pct

def expected_receipts(now, read, users, receipt_state):
    slots = due_slots(now, read, [(11,30),(19,30)])
    if slots is None:
        return "unknown"
    if not users:
        return "unknown"
    states = []
    for user in users:
        for prefix in ("recommendations", "four_rankings"):
            if read(prefix+":preferences:"+user, {}).get("enabled") is not True:
                continue
            for t in slots:
                slot = "morning" if t.hour == 11 else "evening"
                doc = read(f"{prefix}:outbox:{t.date()}:{slot}:{user}", {})
                # Four-mode may legitimately have no eligible report.
                states.append(receipt_state(doc) if doc else ("warning" if prefix=="recommendations" else "unknown"))
    return "warning" if "warning" in states else "unknown" if not states or "unknown" in states else "ok"
