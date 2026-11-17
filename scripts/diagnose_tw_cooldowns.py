"""Read stored annual cooldowns in one database-enforced read-only snapshot.

No worker imports, schema initialization, leases, quotas or provider requests.
Only allowlisted diagnostics and run-local anonymous row numbers leave memory.
"""
import json
import math
import os
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text
from jobs.tw_financial_summary import _diagnosis

TAIPEI = timezone(timedelta(hours=8))


class DiagnosticFailure(Exception):
    def __init__(self, stage, exc):
        from sqlalchemy.exc import OperationalError, ProgrammingError, DBAPIError
        self.stage = stage
        self.category = ('資料庫連線或執行錯誤' if isinstance(exc, OperationalError) else
                         '資料庫查詢格式或權限錯誤' if isinstance(exc, ProgrammingError) else
                         '資料庫驅動錯誤' if isinstance(exc, DBAPIError) else
                         '既有資料型別不符' if isinstance(exc, (TypeError, AttributeError)) else
                         '設定或既有資料格式不符' if isinstance(exc, ValueError) else '未分類錯誤')
        code = getattr(getattr(exc, 'orig', None), 'sqlstate', None)
        # Only known SQLSTATEs, never arbitrary driver strings.
        self.code = code if code in {'25006', '42501', '42P01', '42703', '42601', '08001', '08006', '57014'} else '未提供'
        message = str(exc).lower()
        self.hint = next((label for pattern, label in (
            ('unsupported startup parameter', '連線池不接受啟動參數'),
            ('could not translate host name', '資料庫主機名稱解析失敗'),
            ('name or service not known', '資料庫主機名稱解析失敗'),
            ('timeout expired', '資料庫連線逾時'),
            ('connection refused', '資料庫拒絕連線'),
            ('password authentication failed', '資料庫驗證失敗'),
        ) if pattern in message), '沒有可安全辨識的進一步原因')


def stamp(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value < 253402271999:
        return None
    return value


def date(value):
    value = stamp(value)
    return datetime.fromtimestamp(value, TAIPEI).strftime('%Y-%m-%d %H:%M:%S') if value else '未記錄'


def collect(conn, configured, legacy_users, now):
    def get(key):
        raw = conn.execute(text('SELECT payload FROM documents WHERE key=:key'), {'key': key}).scalar()
        value = json.loads(raw) if raw else {}
        return value if isinstance(value, dict) else {}

    def prefix(value, limit):
        return conn.execute(text('SELECT key, payload FROM documents WHERE key LIKE :prefix ORDER BY key LIMIT :limit'),
                            {'prefix': value + '%', 'limit': limit}).all()

    candidates = set(s.strip().upper() for s in configured.split(',') if s.strip())
    # Match the worker's legacy queue limit (configured symbols do not count).
    requested = set()
    for key, raw in prefix('annual:request:', 100):
        value = json.loads(raw)
        if stamp(value.get('expires')) and value['expires'] > now:
            requested.add(key[len('annual:request:'):])
    for symbol, value in get('annual:requested').items():
        if stamp(value) and now - value < 14 * 86400 and len(requested) < 100:
            requested.add(symbol)
    candidates.update(requested)
    members = prefix('member:', 10001)
    if len(members) > 10000:
        raise ValueError('bounded diagnostic')
    accounts = {key[7:]: json.loads(raw) for key, raw in members}
    users = set(legacy_users) | set(accounts)
    for user in users:
        record = accounts.get(user, {'active': True})
        if record.get('active') and not record.get('password_change_required', False):
            candidates.update(conn.execute(text('SELECT symbol FROM watchlist WHERE "user"=:user'), {'user': user}).scalars())
    symbols = {s.strip().upper() for s in candidates if isinstance(s, str)}
    symbols = sorted({s + '.TW' if s.isdigit() else s for s in symbols})
    symbols = [s for s in symbols if re.fullmatch(r'\d{4}\.(TW|TWO)', s) and get('quote:' + s).get('kind') != 'ETF']
    rows = []
    for index, symbol in enumerate(symbols, 1):
        for field, label in (('eps', 'EPS'), ('roe_pct', 'ROE')):
            rows.append((f'標的 {index:02d}', label, get('mopsfin:feed:' + symbol + ':' + field)))
    return rows, get('annual:source:mopsfin'), get('jobs:tw_financials')


def cooldown(state, now):
    until = stamp(state.get('next_attempt'))
    return ('仍在冷卻' if until > now else '已到期') if until else '未記錄有效期限'


def render(rows, source, last, now):
    lines = ['## 年度 EPS／ROE 唯讀冷卻診斷', '', f'查詢時間：{date(now)}（台灣時間）',
             '僅讀取既有資料；未下載官方資料、寫入資料庫、解除冷卻或使用來源配額。',
             '匿名編號僅適用本次摘要；目前候選清單可能與前次執行不同，無法重建歷史名單。',
             '每個項目僅保存最新狀態；成功可能覆蓋前次失敗，缺少分類時不推測原因。', '']
    count = last.get('total_tasks')
    if type(count) is int and 0 <= count <= 100000:
        lines.append(f'資料庫最近一次批次項目數：{count}；本次候選項目數：{len(rows)}。')
    stage, cause, action = _diagnosis(source)
    lines += [f'來源層級：{cooldown(source, now)}；到期：{date(source.get("next_attempt"))}。',
              f'來源既有診斷：{stage}；{cause}。', '',
              '| 匿名標的 | 項目 | 最新結果 | 冷卻 | 到期（台灣時間） | 最後嘗試／成功時間 | 階段與分類 |',
              '|---|---|---|---|---|---|---|']
    advice = set()
    for label, field, state in rows:
        status = {'ok': '成功後等待', 'failed': '失敗後等待'}.get(state.get('status') if isinstance(state.get('status'), str) else '', '未記錄')
        stage, cause, action = _diagnosis(state)
        if state.get('status') == 'ok':
            stage, cause = '目前為成功狀態', '前次失敗未保留'
        else:
            advice.add(action)
        lines.append(f'| {label} | {field} | {status} | {cooldown(state, now)} | {date(state.get("next_attempt"))} | {date(state.get("last_attempt") if state.get("status") == "failed" else state.get("at"))} | {stage}；{cause} |')
    lines += ['', '建議：冷卻到期僅表示可再嘗試，不代表問題已修復；交由後續既有排程處理。']
    if source:
        advice.add(_diagnosis(source)[2])
    lines.extend('- ' + item for item in sorted(advice))
    return '\n'.join(lines) + '\n'


def read_database(url, configured, legacy_users):
    if not url.startswith(('postgres://', 'postgresql://', 'postgresql+psycopg://')):
        raise ValueError('PostgreSQL required')
    url = url.replace('postgres://', 'postgresql+psycopg://', 1).replace('postgresql://', 'postgresql+psycopg://', 1)
    # Transaction-level READ ONLY also works behind transaction poolers which
    # reject startup options. The first SQL transaction is already read-only.
    engine = create_engine(url, isolation_level='REPEATABLE READ',
                           execution_options={'postgresql_readonly': True},
                           connect_args={'connect_timeout': 10})
    stage = '建立唯讀連線'
    try:
        with engine.connect() as conn:
            stage = '確認資料庫唯讀保護'
            if conn.execute(text('SHOW transaction_read_only')).scalar() != 'on':
                raise ValueError('read-only required')
            conn.execute(text("SET LOCAL statement_timeout = '20s'"))
            now = time.time()
            stage = '讀取既有候選項目與冷卻紀錄'
            rows, source, last = collect(conn, configured, legacy_users, now)
            stage = '產生匿名摘要'
            return render(rows, source, last, now)
    except Exception as exc:
        raise DiagnosticFailure(stage, exc) from None
    finally:
        engine.dispose()


def main():
    try:
        users = json.loads(os.getenv('USER_TOKENS_JSON') or '{}')
        if not isinstance(users, dict) or any(not isinstance(v, str) for v in users.values()):
            raise ValueError('invalid legacy config')
        summary = read_database(os.getenv('DATABASE_URL', ''), os.getenv('ANNUAL_SYMBOLS', ''), users.values())
        result = 0
    except Exception as exc:
        # Never print exceptions: drivers can embed credentials, SQL or payloads.
        summary = '## 年度 EPS／ROE 唯讀冷卻診斷\n\n診斷未完成：唯讀連線、設定或既有資料未通過檢查；未推測到期時間或根因。\n'
        if isinstance(exc, DiagnosticFailure):
            summary += f'階段：{exc.stage}；分類：{exc.category}；SQLSTATE：{exc.code}；提示：{exc.hint}。\n'
        result = 1
    print(summary)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as out:
            out.write(summary)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
