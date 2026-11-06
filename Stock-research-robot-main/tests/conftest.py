import os,tempfile
os.environ['DATABASE_URL']='sqlite:///'+tempfile.mktemp(suffix='.db')
os.environ['USER_TOKENS_JSON']='{"aaaaaaaaaaaaaaaaaaaaaaaa":"Ualice","bbbbbbbbbbbbbbbbbbbbbbbb":"Ubob"}'
os.environ['LINE_CHANNEL_SECRET']='test-secret'
import pytest
from app.db import Base,engine,init_db
@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine);init_db()
    yield
