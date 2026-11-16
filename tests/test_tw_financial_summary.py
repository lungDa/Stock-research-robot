import json
import subprocess

import pytest

from jobs.tw_financial_summary import render_summary, write_summary


def envelope(code='timeout', stage='年度eps下載', **changes):
    return {'state': 'partial', 'result': {
        'state': 'partial', 'official_requests': 1, 'updated_symbols': 0,
        'failed_feeds': 1, 'failures': [{'stage': stage, 'error_code': code}], **changes,
    }}


@pytest.mark.parametrize('code,cause,action', [
    ('timeout', '連線或讀取逾時', '後續排程'),
    ('connection', 'DNS', '連線'),
    ('json', 'JSON', '官方端點'),
    ('budget', '大小或時間預算', '保護上限'),
    ('storage', '資料庫操作失敗', '連線字串'),
    ('contract', '年度數值核對', '不要將缺漏補成 0'),
    ('http_429', '限制請求頻率', '不要反覆重跑'),
    ('http_403', '拒絕存取', '不代表需要新增付費 token'),
    ('http_401', '拒絕存取', '冷卻'),
    ('http_503', '伺服器錯誤', '官方服務狀態'),
    ('http_404', 'HTTP 404', '請求格式'),
])
def test_explains_failure_and_action_in_chinese(code,cause,action):
    text = render_summary(envelope(code))
    assert '年度每股盈餘 EPS：下載' in text
    assert '| 1 | 0 | 1 |' in text
    assert cause in text and action in text
    assert '不代表全市場' in text


def test_contract_reason_uses_exact_allowlisted_explanation():
    data = envelope('contract', '年度roe_pct解析')
    data['result']['failures'][0]['reason'] = '年度roe_pct解析：年度數值單位不符'
    text = render_summary(data)
    assert '年度權益報酬率 ROE：核對' in text and '年度數值單位不符' in text


def test_untrusted_fields_and_markdown_never_reach_summary():
    secret = 'secret-token user@example.test [link](https://private.test) |\n# injected'
    data = envelope(secret, secret, state=secret, official_requests=secret,
                    updated_symbols=True, failed_feeds=-1)
    data['result']['failures'][0].update(reason=secret, symbol=secret, user=secret)
    data['reason'] = data['stderr'] = secret
    text = render_summary(data)
    assert 'secret' not in text and 'injected' not in text and 'private.test' not in text
    assert '| 未提供 | 未提供 | 未提供 |' in text
    assert '無法辨識' in text
    data['result']['failures'] = [{'stage': [], 'error_code': {}, 'reason': secret}]
    data['result']['state'] = []
    assert 'secret' not in render_summary(data)


def test_samples_are_bounded_and_missing_details_are_honest():
    data = envelope(failed_feeds=9)
    data['result']['failures'] *= 9
    text = render_summary(data)
    assert text.count('年度每股盈餘 EPS：下載') == 4
    assert '最多顯示 4 筆' in text and '| 1 | 0 | 9 |' in text
    assert '不能只憑請求次數推斷根因' in render_summary(envelope(failures=[]))


@pytest.mark.parametrize('state,expected', [
    ('cooldown','本次未重新連線'), ('busy','其他更新工作'),
    ('limited','配額恢復'), ('idle','待處理佇列'), ('finished','本批沒有新增資料'),
])
def test_nonfailure_states_do_not_claim_full_coverage(state,expected):
    text = render_summary(envelope(state=state, failures=[], failed_feeds=0))
    assert expected in text and '不代表全市場' in text


def test_missing_metrics_are_not_fabricated_as_zero():
    text = render_summary({'result': {'state': 'cooldown', 'official_requests': 0}})
    assert '| 0 | 未提供 | 未提供 |' in text


def test_parent_timeout_and_abnormal_exit_do_not_invent_source_cause():
    text = render_summary({'state': 'timeout', 'stderr': 'private-token'})
    assert '不能據此判定官方來源逾時' in text and 'private-token' not in text
    assert '無法確認根因或更新筆數' in render_summary({'state': 'failed', 'exit_code': 1})


def test_summary_writer_appends_and_is_optional(monkeypatch,tmp_path,capsys):
    monkeypatch.delenv('GITHUB_STEP_SUMMARY',raising=False)
    write_summary(envelope())
    assert capsys.readouterr().out == ''
    path = tmp_path/'summary.md'
    path.write_text('Existing summary\n',encoding='utf-8')
    monkeypatch.setenv('GITHUB_STEP_SUMMARY',str(path))
    write_summary(envelope())
    assert path.read_text(encoding='utf-8').startswith('Existing summary\n## 台股')
    monkeypatch.setenv('GITHUB_STEP_SUMMARY',str(tmp_path/'private-token'/'missing.md'))
    write_summary(envelope())
    output = capsys.readouterr().out
    assert '更新結果不受影響' in output and 'private-token' not in output


def test_standalone_worker_writes_summary(monkeypatch,tmp_path):
    import runpy
    from jobs import refresh_tw_financials
    from tests.test_mopsfin import payload,seed_metadata
    path = tmp_path/'summary.md'
    seed_metadata()
    monkeypatch.setenv('GITHUB_STEP_SUMMARY',str(path))
    monkeypatch.setenv('ANNUAL_SYMBOLS','6488.TWO')
    monkeypatch.setattr('app.providers.mopsfin.request',lambda path,**kwargs:
        payload('eps' if kwargs['form']['compareItem'] == 'EPS' else 'roe_pct'))
    runpy.run_path(refresh_tw_financials.__file__,run_name='__main__')
    text = path.read_text(encoding='utf-8')
    assert text.count('## 台股年度財務更新') == 1
    assert '| 2 | 1 | 0 |' in text and '本批已結束' in text


@pytest.mark.parametrize('outcome', ['partial', 'timeout', 'exit', 'malformed'])
def test_orchestrator_writes_summary_even_when_financial_step_fails(monkeypatch,tmp_path,outcome):
    from jobs import refresh_data
    path = tmp_path/'summary.md'
    monkeypatch.setenv('GITHUB_STEP_SUMMARY',str(path))
    monkeypatch.setattr(refresh_data,'STEPS',['tw_financials'])
    def run(*args,**kwargs):
        if outcome == 'timeout':
            raise subprocess.TimeoutExpired('worker',65)
        return subprocess.CompletedProcess([],1 if outcome == 'exit' else 0,
            stdout='invalid' if outcome == 'malformed' else json.dumps(envelope()['result']),stderr='')
    monkeypatch.setattr(refresh_data.subprocess,'run',run)
    result = refresh_data.run()
    text = path.read_text(encoding='utf-8')
    assert result['state'] == 'partial'
    assert text.count('## 台股年度財務更新') == 1
    assert ('失敗階段' if outcome == 'partial' else '無法確認根因或更新筆數'
            if outcome != 'timeout' else '執行時間上限') in text
