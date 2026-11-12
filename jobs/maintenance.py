"""Bounded retention for ephemeral records. Financial/user records are excluded."""
import time,json
from datetime import datetime,timezone
from sqlalchemy import select,delete
from app.db import init_db,Session,Document,Lease,ProviderBudget,get,put,leased
from jobs.maintenance_guard import assert_writable

RETENTION={
    'auth:start:':86400,'auth:flow:':86400,'auth:handoff:':86400,'auth:session:':86400,
    'auth:attempt:':2*86400,'auth:password-attempt:':2*86400,
    'public:minute:':2*86400,'public:day:':3*86400,
    'annual:query_minute:':2*86400,'annual:query_day:':3*86400,
    'annual:enqueue_symbol:':86400,'budget:':3*86400,
    'signal:slot:':7*86400,'event:':30*86400,'annual:request:':0,
}


def run(batch_size=2000):
    assert_writable()
    init_db();now=time.time();deleted=0;examined=0
    batch_size=max(1,min(batch_size,2000))
    with leased('maintenance',120) as owned:
        if not owned:return {'state':'busy'}
        # Per-prefix cursors prevent recent or malformed entries starving later expired rows.
        cursors=get('maintenance:cursors',{})
        for prefix,retention in RETENTION.items():
            assert_writable()
            with Session() as s:
                rows=list(s.scalars(select(Document).where(Document.key.startswith(prefix,autoescape=True),
                    Document.key>cursors.get(prefix,'')).order_by(Document.key).limit(batch_size)))
            expired=[]
            for row in rows:
                examined+=1
                try:value=json.loads(row.payload)
                except (ValueError,TypeError):continue
                if not isinstance(value,dict):continue
                expires=value.get('expires')
                at=value.get('at')
                # An active session must never be removed, even when its
                # creation timestamp is old. Prefer explicit expiry over age.
                if prefix=='auth:session:' and type(expires) not in (int,float):continue
                if type(expires) in (int,float):
                    deadline=expires+retention
                elif type(at) in (int,float):
                    deadline=at+retention
                else:
                    continue
                if now>deadline:expired.append(row.key)
            if expired:
                assert_writable()
                with Session.begin() as s:s.execute(delete(Document).where(Document.key.in_(expired)))
                deleted+=len(expired)
            cursors[prefix]=rows[-1].key if len(rows)==batch_size else ''
        assert_writable()
        with Session.begin() as s:
            s.execute(delete(Lease).where(Lease.expires_at<now-86400))
            s.execute(delete(ProviderBudget).where(ProviderBudget.expires_at<now))
        result={'updated_at':datetime.now(timezone.utc).isoformat(),'deleted':deleted,'examined':examined}
        assert_writable()
        put('maintenance:cursors',cursors);put('jobs:maintenance',result)
        return result


if __name__=='__main__':print(run())
