from pathlib import Path
from unittest.mock import Mock
import pytest
from app.db import get,put
import jobs.refresh_universe as job

def test_universe_refresh_from_small_snapshot(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(job,'snapshot',lambda market:{'2330':{'name':'台積電'},'00679B':{'name':'ETF'},'123456':{'name':'權證'},'_meta':{'complete':True}})
    job.build()
    text=Path('data/universe.csv').read_text()
    assert '2330.TW' in text and '00679B.TWO' in text and '123456' not in text

def test_empty_source_preserves_original(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path);Path('data').mkdir();f=Path('data/universe.csv');f.write_text('original')
    monkeypatch.setattr(job,'snapshot',Mock(side_effect=RuntimeError('offline')))
    with pytest.raises(RuntimeError): job.build()
    assert f.read_text()=='original'

def test_weekly_master_reuses_database_cache(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    loader=Mock(return_value={'2330':{'name':'台積電'},'_meta':{'complete':True}})
    monkeypatch.setattr(job,'snapshot',loader)
    job.build();job.build()
    assert loader.call_count==2  # 上市、上櫃各一次，不是每次建立各打一遍

def test_partial_snapshot_is_disclosed(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(job,'snapshot',lambda market:{'00411A':{'name':'主動ETF'},'_meta':{'complete':False}})
    job.build()
    assert get('universe:scope')['partial'] is True
    assert '00411A.TWO' in Path('data/universe.csv').read_text()
