"""Offline cases, not captured official responses; do not infer a live schema."""
from unittest.mock import Mock

import pytest

from app.db import get, put
from app.providers.mopsfin import parse_annual
from jobs import refresh_tw_financials as job
from jobs.tw_financial_summary import render_summary
from tests.test_mopsfin import DISPLAY, TODAY, payload, seed_metadata


@pytest.mark.parametrize('field', ['eps', 'roe_pct'])
@pytest.mark.parametrize('display', ['2330 台積電', '64880 其他', '6488', '', None, {}])
def test_display_cannot_bind_another_company_to_requested_symbol(field, display):
    body = payload(field, display if isinstance(display, str) else DISPLAY)
    with pytest.raises(ValueError, match='Verified company display mismatch'):
        parse_annual(body, '6488.TWO', field, display, TODAY)


@pytest.mark.parametrize('field', ['eps', 'roe_pct'])
def test_normalized_verified_display_retains_exact_code_binding(field):
    result = parse_annual(payload(field), '6488.TWO', field, '６４８８\u3000環球晶', TODAY)
    assert result['2025'][field] == 4.5
    assert result['2025']['field_sources'][field]['request']['companyId'] == DISPLAY


@pytest.mark.parametrize('key', ['displayCompanyId', 'checkedNameList'])
@pytest.mark.parametrize('value,category', [
    (DISPLAY, 'type'), ({'private-token': DISPLAY}, 'type'),
    ([DISPLAY, DISPLAY], 'count'), (['2330 台積電'], 'identity'),
    (['6488 private-token'], 'identity'),
])
def test_identity_metadata_errors_identify_field_and_failure_kind(key, value, category):
    body = payload()
    body[key] = value
    with pytest.raises(ValueError, match=key + ' metadata ' + category + ' mismatch'):
        parse_annual(body, '6488.TWO', 'eps', DISPLAY, TODAY)


def test_company_name_alone_still_cannot_prove_code():
    body = payload()
    body['graphData'][0]['label'] = '環球晶'
    body['displayCompanyId'] = []
    body['checkedNameList'] = ['環球晶']
    with pytest.raises(ValueError, match='Company code cannot be bound'):
        parse_annual(body, '6488.TWO', 'eps', DISPLAY, TODAY)


@pytest.mark.parametrize('key', ['displayCompanyId', 'checkedNameList'])
def test_worker_preserves_cache_and_summary_exposes_only_fixed_diagnosis(monkeypatch, key):
    seed_metadata()
    original = {'rows': {'2025': {'eps': 7}}}
    put('financial:official:6488.TWO', original)
    body = payload()
    secret = 'token=private-token user@example.test'
    body[key] = secret
    monkeypatch.setattr(job, 'request', Mock(return_value=body))
    result = job.run(['6488.TWO'], max_requests=1)
    assert result['failed_feeds'] == 1 and result['updated_symbols'] == 0
    assert get('financial:official:6488.TWO') == original
    detail = result['failures'][0]
    assert detail['error_code'] == 'contract' and '不是預期的陣列' in detail['reason']
    summary = render_summary({'result': result})
    assert key in summary and '不是預期的陣列' in summary
    assert secret not in summary and '6488' not in summary


@pytest.mark.parametrize('field', ['eps', 'roe_pct'])
def test_observed_official_market_industry_suffix(field):
    body = payload(field)
    body['graphData'][0]['label'] = '環球晶'
    body['displayCompanyId'] = ['6488 環球晶 (上櫃半導體業)']
    body['checkedNameList'] = ['6488 環球晶 (上櫃半導體業)']
    assert parse_annual(body, '6488.TWO', field, DISPLAY, TODAY)['2025'][field] == 4.5


@pytest.mark.parametrize('invalid', [
    '6488 環球晶 (上市半導體業)',
    '6488 其他公司 (上櫃半導體業)',
    '2330 環球晶 (上櫃半導體業)',
    '6488 環球晶 (其他內容)',
])
def test_annotated_identity_still_rejects_mismatch(invalid):
    body = payload()
    body['graphData'][0]['label'] = '環球晶'
    body['displayCompanyId'] = [invalid]
    body['checkedNameList'] = [invalid]
    with pytest.raises(ValueError, match='displayCompanyId metadata identity mismatch'):
        parse_annual(body, '6488.TWO', 'eps', DISPLAY, TODAY)
