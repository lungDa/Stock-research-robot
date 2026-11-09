"""Bounded persistent symbol requests. No watches, subscriptions, or user IDs."""
import time
from app.db import get,put,leased,documents_with_prefix

PREFIX='annual:request:'


def requested():
    now=time.time()
    rows={k[len(PREFIX):]:v for k,v in documents_with_prefix(PREFIX,100).items() if v.get('expires',0)>now}
    # Read old installations once without requiring a manual migration.
    for symbol,stamp in get('annual:requested',{}).items():
        if now-stamp<14*86400 and len(rows)<100:
            rows.setdefault(symbol,{'requested_at':stamp,'expires':stamp+14*86400})
    return rows


def enqueue(symbol):
    now=time.time()
    with leased('annual:enqueue',10) as owned:
        if not owned:return False
        from app.db import Session,Document
        from sqlalchemy import delete
        expired=[k for k,v in documents_with_prefix(PREFIX,200).items() if v.get('expires',0)<=now]
        if expired:
            with Session.begin() as session:session.execute(delete(Document).where(Document.key.in_(expired)))
        rows=requested()
        if symbol not in rows and len(rows)>=100:return False
        put(PREFIX+symbol,{'requested_at':now,'expires':now+14*86400})
        return True


def source_slot(source, cap):
    from app.db import reserve_budget
    from app.services.freshness import local_now
    return reserve_budget(source+':'+str(local_now().date()),cap)
