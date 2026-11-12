import pytest
from jobs import v26_official_catalog as catalog


def test_parse_official_company_registry():
    rows = [{'公司代號': '2330', '公司名稱': '台積電'},
            {'公司代號': '0050', '公司名稱': '基金'}, {'公司代號': '6488', '公司名稱': '環球晶'}]
    result = catalog.parse_companies(rows)
    assert result['2330']['kind'] == 'STOCK'
    assert '0050' in result  # Never infer ETF status from a code prefix.
    assert len(result) == 3


def test_reject_unknown_schema_and_empty():
    with pytest.raises(ValueError):
        catalog.parse_companies([{'stock_id': '2330'}])
    with pytest.raises(ValueError):
        catalog.parse_companies([])


def test_failure_preserves_prior_catalog(monkeypatch):
    writes = []
    monkeypatch.setattr(catalog, 'get', lambda key, default=None: {})
    monkeypatch.setattr(catalog, 'put', lambda key, value: writes.append(key))
    def fail(*args, **kwargs):
        raise TimeoutError('offline')
    with pytest.raises(TimeoutError):
        catalog.refresh('TW', now=1800000000, fetcher=fail)
    assert writes == ['v26:catalog:error:TW']


def test_success_persists_provenance(monkeypatch):
    writes = {}
    monkeypatch.setattr(catalog, 'get', lambda key, default=None: {})
    monkeypatch.setattr(catalog, 'put', lambda key, value: writes.update({key: value}))
    catalog.refresh('TWO', now=1800000000,
                    fetcher=lambda *args, **kwargs: [{'公司代號': '6488', '公司名稱': '環球晶'}])
    record = writes['official:catalog:TWO']
    assert record['source'] == catalog.ENDPOINTS['TWO']
    assert record['scope'] == 'OFFICIAL_COMPANY_REGISTRY'
    assert record['complete'] is False
