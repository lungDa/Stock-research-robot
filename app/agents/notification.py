"""Pure shadow audit of existing ranking outboxes; never sends messages."""
from collections import Counter
from datetime import timedelta
from zoneinfo import ZoneInfo
from app.services.trading_calendar import session

PREFIXES=("recommendations","four_rankings")

def inspect_outbox(doc, now, same_day):
    if not isinstance(doc,dict) or not isinstance(doc.get("messages"),list) or not doc["messages"] or len(doc["messages"])>100:
        return "unknown","review_evidence",0
    messages=doc["messages"]
    if any(not isinstance(m,dict) for m in messages):
        return "unknown","review_evidence",0
    keys=[m.get("retry_key") for m in messages]
    if any(not isinstance(k,str) or not k for k in keys) or len(set(keys))!=len(keys):
        return "duplicate_risk","hold_and_review",0
    accepted=0
    for m in messages:
        r=m.get("acceptance")
        valid=isinstance(r,dict) and ((r.get("status_code")==200 and bool(r.get("request_id"))) or (r.get("status_code")==409 and bool(r.get("accepted_request_id"))))
        if valid:
            accepted+=1
        if m.get("sent") is True and not valid or valid and m.get("sent") is not True:
            return "receipt_uncertain","hold_and_review",accepted
    if accepted==len(messages):
        return "api_accepted_only","do_not_resend",accepted
    at=doc.get("created_at")
    if type(at) not in (int,float) or not 0<=now.timestamp()-at<23*3600 or not same_day:
        return "expired_or_unknown","manual_review",accepted
    return ("partial" if accepted else "pending"),"review_existing_retry_keys",accepted

class NotificationAgent:
    def audit(self, *, now, read, users, days=7):
        if now.tzinfo is None or type(days) is not int or not 1<=days<=14 or not isinstance(users,(list,tuple)) or len(users)>100 or any(not isinstance(u,str) or not u for u in users):
            raise ValueError("invalid audit scope")
        now=now.astimezone(ZoneInfo("Asia/Taipei"))
        history=[]
        for offset in range(days):
            day=now.date()-timedelta(days=offset)
            trading=session(day,read)
            for slot,h in (("morning",11),("evening",19)):
                due=now.replace(year=day.year,month=day.month,day=day.day,hour=h,minute=30,second=0,microsecond=0)
                if due+timedelta(minutes=45)>now or trading is False:
                    continue
                for prefix in PREFIXES:
                    counts=Counter()
                    advice=Counter()
                    accepted=0
                    for user in set(users):
                        doc=read(f"{prefix}:outbox:{day}:{slot}:{user}",None)
                        if doc is not None:
                            state,action,n=inspect_outbox(doc,now,day==now.date())
                        else:
                            pref=read(f"{prefix}:preferences:{user}",{})
                            if not isinstance(pref,dict) or pref.get("enabled") is not True:
                                continue
                            state="possible_missing" if trading is True and prefix=="recommendations" else "unknown"
                            action="verify_subscription_and_schedule"
                            n=0
                        counts[state]+=1
                        advice[action]+=1
                        accepted+=n
                    history.append({"date":str(day),"slot":slot,"report":prefix,"calendar_known":trading is not None,"counts":dict(counts),"recommendations":dict(advice),"accepted_messages":accepted})
        return {"mode":"shadow","status":"complete","delivery_verified":False,"scope":"current_subscribers_and_cached_outboxes","history":history}
