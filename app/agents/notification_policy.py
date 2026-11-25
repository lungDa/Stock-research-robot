"""Isolated evidence contracts; no persistence or sender."""
from datetime import date
from collections import Counter
from app.agents.notification import inspect_outbox

CRONS={"30 3 * * 1-5":"morning","30 11 * * 1-5":"evening","7,37 4-15 * * 1-5":"compensation","17 10 * * 1-5":"daily_scan"}

def subscription_snapshot(doc,day,slot,report):
    if not isinstance(doc,dict) or doc.get("version")!=1 or doc.get("date")!=str(day) or doc.get("slot")!=slot or doc.get("report")!=report or doc.get("complete") is not True:
        return None
    users=doc.get("eligible_users")
    if not isinstance(users,list) or len(users)>100 or any(not isinstance(u,str) or not u or len(u)>128 for u in users) or len(set(users))!=len(users):return None
    return frozenset(users)

def cron_evidence(event,cron=None):
    if event=="schedule":return CRONS.get(cron,"unknown_schedule")
    return {"workflow_dispatch":"manual_preview_or_send","workflow_run":"upstream_wakeup"}.get(event,"unknown")

def error_evidence(doc):
    if not isinstance(doc,dict) or doc.get("version")!=1:return "unknown"
    code=doc.get("http_status")
    if code==429:return "rate_limited"
    if doc.get("reason")=="quota_exhausted":return "quota_exhausted"
    if code in (401,403):return "authorization_error"
    if type(code) is int and 500<=code<=599:return "upstream_error"
    return "unknown"

def recovery_advice(doc,now,*,same_day,eligible=None,duplicate=False,error="unknown"):
    state,_,_=inspect_outbox(doc,now,same_day)
    if state=="api_accepted_only":return "do_not_resend"
    if duplicate or state in ("duplicate_risk","receipt_uncertain"):return "hold_and_review"
    if eligible is not True or not same_day:return "manual_review"
    if error in ("rate_limited","quota_exhausted","authorization_error"):return "hold_and_review"
    if state in ("partial","pending"):return "review_existing_retry_keys"
    return "manual_review"

def paged(fetch,*,max_pages=3, collection="jobs"):
    """Fixed caller endpoint; incomplete or duplicate results never claim coverage."""
    rows=[];seen=set();total=None
    for page in range(1,max_pages+1):
        try:
            doc=fetch(page)
            items=doc[collection];count=doc["total_count"]
            if type(count) is not int or count<0 or not isinstance(items,list) or len(items)>100 or (total is not None and total!=count):break
            total=count
            for item in items:
                key=item["id"]
                if type(key) is not int or key in seen:return rows,False
                seen.add(key);rows.append(item)
            if len(rows)==total:return rows,True
            if not items or len(rows)>total:break
        except Exception:break
    return rows,False


def isolated_evidence(*, snapshot, day, slot, report, user, event, cron, error, outbox, now, duplicate=False):
    users=subscription_snapshot(snapshot,day,slot,report)
    eligible=None if users is None else user in users
    failure=error_evidence(error)
    from zoneinfo import ZoneInfo
    return {"mode":"shadow","eligible":eligible,"trigger":cron_evidence(event,cron),"error":failure,"advice":recovery_advice(outbox,now,same_day=day==now.astimezone(ZoneInfo("Asia/Taipei")).date(),eligible=eligible,duplicate=duplicate,error=failure)}
