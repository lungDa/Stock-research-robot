from pathlib import Path
from unittest.mock import Mock
import pandas as pd
import pytest
import jobs.refresh_universe as job

def setup_sources(monkeypatch,empty=False):
    def response(url,**kwargs):
        r=Mock();r.text='ignored' if 'isin.twse' in url else 'Symbol|Security Name|Test Issue\nAAPL|Apple|N\n'
        if 'otherlisted' in url: r.text='ACT Symbol|Security Name|Test Issue\nVOO|Vanguard ETF|N\n'
        return r
    monkeypatch.setattr(job.requests,'get',response)
    monkeypatch.setattr(job.pd,'read_html',lambda *a,**k:[pd.DataFrame([] if empty else [['2330　台積電','ISIN','date','market','industry','ESVUFR']])])

def test_universe_refresh(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path);Path('data').mkdir()
    setup_sources(monkeypatch)
    job.build()
    text=Path('data/universe.csv').read_text()
    assert '2330.TW' in text and '2330.TWO' in text and 'AAPL' in text and 'VOO' in text

def test_empty_source_preserves_original(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path);Path('data').mkdir()
    file=Path('data/universe.csv');file.write_text('original')
    setup_sources(monkeypatch,empty=True)
    with pytest.raises(RuntimeError): job.build()
    assert file.read_text()=='original'


def test_taiwan_alphanumeric_etf_in_universe(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path);Path('data').mkdir()
    setup_sources(monkeypatch)
    monkeypatch.setattr(job.pd,'read_html',lambda *a,**k:[pd.DataFrame([['00679B　元大美債20年','ISIN','date','market','industry','CEOGEU']])])
    job.build()
    assert '00679B.TWO' in Path('data/universe.csv').read_text()
