import json
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Text, Boolean, UniqueConstraint
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
def init_db(): Base.metadata.create_all(engine)
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
