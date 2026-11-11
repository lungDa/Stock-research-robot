import json
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Text, Boolean, UniqueConstraint, Float
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from app.config import settings
url=settings.database_url.replace('postgres://','postgresql+psycopg://',1)
if url.startswith('postgresql://'): url=url.replace('postgresql://','postgresql+psycopg://',1)
engine=create_engine(url,pool_pre_ping=True,connect_args={'check_same_thread':False} if url.startswith('sqlite') else {})
Session=sessionmaker(engine,expire_on_commit=False)
class Base(DeclarativeBase): pass
class Watch(Base):
    __tablename__='watchlist'
    id:Mapped[int]=mapped_column(primary_key=True)
    user:Mapped[str]=mapped_column(String(100))
    symbol:Mapped[str]=mapped_column(String(30))
    __table_args__=(UniqueConstraint('user','symbol'),)
class Preference(Base):
    __tablename__='preferences'
    user:Mapped[str]=mapped_column(String(100),primary_key=True)
    enabled:Mapped[bool]=mapped_column(Boolean,default=False)
class Document(Base):
    __tablename__='documents'
    key:Mapped[str]=mapped_column(String(240),primary_key=True)
    payload:Mapped[str]=mapped_column(Text)
class Lease(Base):
    __tablename__='worker_leases'
    key:Mapped[str]=mapped_column(String(240),primary_key=True)
    owner:Mapped[str]=mapped_column(String(64))
    expires_at:Mapped[float]=mapped_column(Float,index=True)
class ProviderBudget(Base):
    __tablename__='provider_budgets'
    key:Mapped[str]=mapped_column(String(100),primary_key=True)
    used:Mapped[int]=mapped_column(default=0)
    expires_at:Mapped[float]=mapped_column(Float,index=True)
def init_db():
    from app.trading import models, fees  # register paper tables before metadata creation
    from app.day_trader import access_models  # register V2.5 access-control tables
    from app.api import device_sessions  # register device session table
    Base.metadata.create_all(engine)
def put(key,value):
    with Session.begin() as s: s.merge(Document(key=key,payload=json.dumps(value,ensure_ascii=False,allow_nan=False)))
def get(key,default=None):
    with Session() as s:
        row=s.get(Document,key)
        return json.loads(row.payload) if row else default
def claim(key,value):
    from sqlalchemy.exc import IntegrityError
    try:
        with Session.begin() as s: s.add(Document(key=key,payload=json.dumps(value)))
        return True
    except IntegrityError: return False

def get_many(keys):
    from sqlalchemy import select
    keys=list(dict.fromkeys(keys))
    if len(keys)>80:raise ValueError('最多80個快取鍵')
    with Session() as s:
        return {r.key:json.loads(r.payload) for r in s.scalars(select(Document).where(Document.key.in_(keys)))}


def documents_with_prefix(prefix, limit=100):
    from sqlalchemy import select
    with Session() as s:
        return {r.key:json.loads(r.payload) for r in s.scalars(
            select(Document).where(Document.key.startswith(prefix, autoescape=True)).order_by(Document.key).limit(limit))}


def acquire_lease(key, seconds=180):
    """Atomic across processes and hosts, with bounded crash recovery."""
    import time,secrets
    from sqlalchemy import update
    from sqlalchemy.exc import IntegrityError
    now=time.time();owner=secrets.token_hex(16)
    with Session.begin() as s:
        changed=s.execute(update(Lease).where(Lease.key==key,Lease.expires_at<=now)
                          .values(owner=owner,expires_at=now+seconds)).rowcount
    if changed:return owner
    try:
        with Session.begin() as s:s.add(Lease(key=key,owner=owner,expires_at=now+seconds))
        return owner
    except IntegrityError:return None


def release_lease(key, owner):
    from sqlalchemy import delete
    with Session.begin() as s:s.execute(delete(Lease).where(Lease.key==key,Lease.owner==owner))


def reserve_budget(key, cap):
    """Two statements, independent of the size of the daily quota."""
    import time
    from sqlalchemy import update
    if engine.dialect.name=='postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    with Session.begin() as s:
        s.execute(insert(ProviderBudget).values(key=key,used=0,expires_at=time.time()+3*86400)
                  .on_conflict_do_nothing(index_elements=['key']))
        return bool(s.execute(update(ProviderBudget).where(ProviderBudget.key==key,ProviderBudget.used<cap)
                    .values(used=ProviderBudget.used+1)).rowcount)


from contextlib import contextmanager
@contextmanager
def leased(key,seconds=180):
    owner=acquire_lease(key,seconds)
    try:yield bool(owner)
    finally:
        if owner:release_lease(key,owner)
