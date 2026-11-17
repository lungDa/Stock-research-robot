import json
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, text, event

from scripts import diagnose_tw_cooldowns as diag

NOW = 1794895200


def test_selection_and_snapshot_are_read_only():
    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE documents (key TEXT PRIMARY KEY, payload TEXT)'))
        conn.execute(text('CREATE TABLE watchlist ("user" TEXT, symbol TEXT)'))
        docs = {
            'annual:request:6488.TWO': {'expires': NOW + 1},
            'annual:request:9999.TW': {'expires': NOW - 1},
            'annual:requested': {'1234.TW': NOW - 1, '9876.TW': NOW - 15 * 86400},
            'member:private-user': {'active': True},
            'member:inactive': {'active': False},
            'member:password': {'active': True, 'password_change_required': True},
            'quote:0050.TW': {'kind': 'ETF'},
            'mopsfin:feed:2330.TW:eps': {'status': 'failed', 'next_attempt': NOW + 60},
            'jobs:tw_financials': {'total_tasks': 10},
        }
        for key, value in docs.items():
            conn.execute(text('INSERT INTO documents VALUES (:key, :payload)'), {'key': key, 'payload': json.dumps(value)})
        for user, symbol in [('private-user', '5678.TW'), ('inactive', '8888.TW'), ('password', '7777.TW'), ('legacy', '4321.TW')]:
            conn.execute(text('INSERT INTO watchlist VALUES (:user, :symbol)'), {'user': user, 'symbol': symbol})
    with engine.connect() as conn:
        conn.execute(text('PRAGMA query_only=ON'))
        statements = []
        event.listen(conn, 'before_cursor_execute', lambda c, cur, sql, p, ctx, many: statements.append(sql))
        rows, source, last = diag.collect(conn, '2330,0050.TW,AAPL,6488.TWO', ['legacy'], NOW)
        assert len(rows) == 10 and last['total_tasks'] == 10
        assert sum(s.get('status') == 'failed' for _, _, s in rows) == 1
        assert all(sql.startswith('SELECT ') for sql in statements)
        assert 'private-user' not in diag.render(rows, source, last, NOW)
        with pytest.raises(Exception):
            conn.execute(text('DELETE FROM documents'))


def test_safe_summary_distinguishes_success_failure_expiry_and_missing():
    secret = 'token=SECRET <script>private-user</script>'
    rows = [
        ('標的 01', 'EPS', {'status': 'ok', 'next_attempt': NOW + 86400, 'at': NOW - 10}),
        ('標的 01', 'ROE', {'status': 'failed', 'next_attempt': NOW, 'last_attempt': NOW - 86400,
                          'stage': '年度roe_pct解析', 'error_code': 'contract',
                          'reason': '年度roe_pct解析：年度數值單位不符'}),
        ('標的 02', 'EPS', {'stage': secret, 'error_code': secret, 'reason': secret, 'next_attempt': secret}),
    ]
    result = diag.render(rows, {'next_attempt': NOW + 60, 'error_code': 'http_429'}, {}, NOW)
    assert secret not in result and '2330' not in result
    assert all(word in result for word in ['成功後等待', '失敗後等待', '仍在冷卻', '已到期', '未記錄有效期限', '年度數值單位不符', 'HTTP 429'])


@pytest.mark.parametrize('value', [None, True, {}, [], float('nan'), float('inf'), -1, 10**30, 'secret'])
def test_untrusted_timestamp(value):
    assert diag.date(value) == '未記錄'


def test_connection_enforces_read_only_and_disposes(monkeypatch):
    # Use a context manager mock so the actual production entry can be tested.
    from unittest.mock import MagicMock
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.execute.return_value.scalar.return_value = 'on'
    factory = Mock(return_value=engine)
    monkeypatch.setattr(diag, 'create_engine', factory)
    monkeypatch.setattr(diag, 'collect', Mock(return_value=([], {}, {})))
    diag.read_database('postgres://user:secret@example/db', '', [])
    options = factory.call_args.kwargs
    assert options['isolation_level'] == 'REPEATABLE READ'
    assert 'default_transaction_read_only=on' in options['connect_args']['options']
    engine.dispose.assert_called_once()
    engine.connect.return_value.__enter__.return_value.execute.return_value.scalar.return_value = 'off'
    diag.collect.reset_mock()
    with pytest.raises(ValueError):
        diag.read_database('postgres://user:secret@example/db', '', [])
    diag.collect.assert_not_called()


def test_failure_never_prints_exception_or_credentials(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv('USER_TOKENS_JSON', '{}')
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(tmp_path / 'summary.md'))
    monkeypatch.setattr(diag, 'read_database', Mock(side_effect=RuntimeError('token=SECRET private-user database-url')))
    assert diag.main() == 1
    output = capsys.readouterr().out
    assert '診斷未完成' in output and 'SECRET' not in output and 'private-user' not in output
    assert (tmp_path / 'summary.md').read_text(encoding='utf-8').strip() == output.strip()
