import os,tempfile
os.environ['DATABASE_URL']='sqlite:///'+tempfile.mktemp(suffix='.db')
os.environ['USER_TOKENS_JSON']='{"aaaaaaaaaaaaaaaaaaaaaaaa":"Ualice","bbbbbbbbbbbbbbbbbbbbbbbb":"Ubob"}'
os.environ['LINE_CHANNEL_SECRET']='test-secret'
import pytest
from app.db import Base,engine,init_db
@pytest.fixture(autouse=True)
def clean_db(monkeypatch):
    # Simulated refresh failures must not pollute the real CI job summary.
    monkeypatch.delenv('GITHUB_STEP_SUMMARY',raising=False)
    Base.metadata.drop_all(engine);init_db()
    yield


@pytest.fixture
def taiwan_market(monkeypatch):
    """Synthetic weekday-only exchange calendar for tests unrelated to calendars."""
    from app.db import put
    from app.services import freshness
    from datetime import datetime, timedelta
    now=freshness.local_now().replace(hour=14,minute=0,second=0,microsecond=0)
    # Most tests using this fixture assume a completed synthetic trading day.
    while now.weekday() >= 5:
        now -= timedelta(days=1)
    class FixtureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)
    # Patch the clock behind local_now, including already-imported references.
    monkeypatch.setattr(freshness,'datetime',FixtureClock)
    for year in {2025,2026,2027,now.year,now.year-1}:
        put('recommendations:calendar:'+str(year),{'year':year,'closed':[],'opened':[],'at':0})


@pytest.fixture
def verified_actions():
    """Install explicit empty event coverage for synthetic price histories only."""
    from app.db import put
    from app.providers.corporate_actions import FEEDS
    def install(symbol,start,end):
        for feed in FEEDS:
            put('corporate:feed:'+symbol+':'+feed,{'status':'ok','events':[],
                'coverage_windows':[{'start':start,'end':end}]})
    return install

