from app.day_trader.reporting import summary

def test_missing_report_does_not_send():
    assert summary({}) is None
    assert summary({"rankings":{}}) is None

def test_empty_lists_report_data_gap_not_fake_top_ten():
    text=summary({"as_of":"2026-11-11","rankings":{}})
    assert text.count("資料不足，暫不排名")==4
    assert "研究用途" in text


def test_cache_refresh_partial_data_and_tenant_scope(monkeypatch):
    from app.day_trader.reporting import refresh_cached,latest
    from app.services import watchlist,research,multifactor
    from app.services.freshness import local_now
    day=str(local_now().date())
    monkeypatch.setattr(watchlist,'watches',lambda user:['2330.TW','2317.TW','6488.TWO'])
    def quotes(symbols):
        return [{'symbol':s,'date':day,'price':100,'rating':{'checks':[
            {'metric':'eps_latest','weight':10,'passed':True if s=='2330.TW' else None},
            {'metric':'price_ma20','weight':10,'passed':True}]}} for s in symbols[:2]]
    monkeypatch.setattr(research,'quotes_for',quotes)
    monkeypatch.setattr(multifactor,'rated_many',lambda rows,user:rows)
    report=refresh_cached('alice')
    assert [r['symbol'] for r in report['rankings']['combined']]==['2330.TW']
    assert report['skipped']['missing_quote']==1
    assert report['skipped']['missing_fundamentals']==1
    assert report['rankings']['intraday']==[]
    assert latest('bob')=={}
    assert latest('alice')==report
    assert not any(refresh_cached('alice','2000-01-01')['rankings'].values())


def test_four_only_subscriber_generates_report_without_market_fetch(monkeypatch):
    from jobs import recommend
    from app.day_trader import reporting
    from app.services.freshness import local_now
    day=local_now().date()
    monkeypatch.setattr(recommend,'is_session',lambda d:True)
    monkeypatch.setattr(recommend,'target_day',lambda d,slot:day)
    monkeypatch.setattr(recommend,'member_users',lambda:['alice'])
    monkeypatch.setattr(recommend,'can_use_personal',lambda u:True)
    monkeypatch.setattr(recommend,'preferences',lambda u:{'enabled':False})
    monkeypatch.setattr(reporting,'preferences',lambda u:{'enabled':True})
    monkeypatch.setattr(reporting,'refresh_cached',lambda u,d:{'as_of':d,'rankings':{'long_term':[{'symbol':'2330.TW'}]}})
    result=recommend.run('morning',dry_run=True)
    assert result['four_reports']==1
    assert result['reports']==[]
