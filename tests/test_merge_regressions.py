from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from app.ui.query_link import apply_symbol_link


def test_recommendation_link_selects_stock_and_clears_stale_result_once():
    from app.services.recommendation_flex import recommendation_flex
    from urllib.parse import urlsplit, parse_qs
    card = recommendation_flex([{'symbol':'6488.TWO'}], 'https://example.com')
    link = card['contents']['contents'][0]['footer']['contents'][0]['action']['uri']
    params = {k:v[0] for k,v in parse_qs(urlsplit(link).query).items()}
    state = {'result':{'symbol':'2330.TW'}, 'download_pending':True}
    assert apply_symbol_link(params,state)=='6488.TWO'
    assert state['query_symbol']=='6488.TWO' and 'result' not in state
    assert not state['download_pending']
    state['query_symbol']='AAPL'
    state['result']={'symbol':'AAPL'}
    apply_symbol_link(params,state)
    assert state['query_symbol']=='AAPL' and state['result']['symbol']=='AAPL'


@pytest.mark.parametrize('value', [None, ['6488.TWO'], '../admin', '2330.TW&token=secret', 'https://example.com', ''])
def test_invalid_link_does_not_change_selection(value):
    state={'query_symbol':'2330'}
    assert apply_symbol_link({'symbol':value},state) is None
    assert state=={'query_symbol':'2330'}


def test_single_cash_request_rotates_all_years_in_even_sized_history(monkeypatch):
    from jobs import refresh_cash_dividends as job
    from tests.test_cashflow_report import seed_catalog, report
    from app.services.freshness import local_now
    seed_catalog()
    years=[]
    def download(path,**kwargs):
        year=int(kwargs['form']['ys'][:4])
        years.append(year)
        return report(['2330.TW'],year=year)
    monkeypatch.setattr(job,'request',download)
    for _ in range(4):job.run(['2330.TW'],max_requests=1,years=4)
    assert years==list(range(local_now().year-1,local_now().year-5,-1))


def test_annual_lease_covers_slow_preparation_and_parent_timeout(monkeypatch):
    from jobs import refresh_annual as job
    import app.db as db
    @contextmanager
    def check(key,seconds):
        assert key=='annual:worker' and seconds>90
        yield True
    monkeypatch.setattr(db,'leased',check)
    monkeypatch.setattr(job,'_run',Mock(return_value={'state':'finished'}))
    job.run([],query=True)


def test_cash_lease_covers_parent_timeout(monkeypatch):
    from jobs import refresh_cash_dividends as job
    @contextmanager
    def check(key,seconds):
        assert key=='annual:worker' and seconds>90
        yield False
    monkeypatch.setattr(job,'leased',check)
    assert job.run(['2330.TW'])['state']=='busy'
