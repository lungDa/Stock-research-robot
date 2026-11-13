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


def prioritize_missing(candidates, now=None, starvation_days=3):
    """Order incomplete symbols by fewest missing fields, without starving older work.

    candidates: iterable of dicts with symbol, missing_fields, requested_at.
    This function is pure; callers persist queue state and perform bounded fetches.
    """
    now=time.time() if now is None else now
    if starvation_days<=0:raise ValueError('starvation_days must be positive')
    unique={}
    for row in candidates:
        if not isinstance(row,dict) or not row.get('symbol'):continue
        symbol=row['symbol']
        try:
            missing=int(row['missing_fields'])
            requested=float(row.get('requested_at',now))
        except (KeyError,TypeError,ValueError,OverflowError):continue
        if missing<0 or not (float('-inf')<requested<float('inf')):continue
        entry={'symbol':symbol,'missing_fields':missing,'requested_at':requested}
        if symbol not in unique or (missing,requested)<(
                unique[symbol]['missing_fields'],unique[symbol]['requested_at']):
            unique[symbol]=entry
    def priority(row):
        age=max(0,now-row['requested_at'])
        # Every waiting interval compensates for one missing field.
        effective=max(0,row['missing_fields']-int(age//(starvation_days*86400)))
        return (effective,row['requested_at'],row['symbol'])
    return sorted(unique.values(),key=priority)
