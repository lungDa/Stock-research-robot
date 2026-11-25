"""One opted-in watchlist report per trading day, with durable retry keys."""
import math
from app.db import get, init_db, leased
from app.channels.line import quota
from app.services import assistant
from app.services.accounts import can_use_personal
from app.services.freshness import local_now
from app.services.market_recommendations import is_session
from app.services.watchlist import subscribed, watches
from jobs.recommend import deliver


def report(user, day, symbols):
    rows = {row['symbol']: row for row in assistant.personal_ratings(user)}
    lines = [f'股海燈塔｜每日追蹤報告 {day}', '行情以快取收盤價為準，非即時報價。']
    for symbol in symbols:
        row = rows.get(symbol)
        if not row or row.get('price') is None:
            lines.append(f'{symbol}｜行情不足')
            continue
        price, date = row['price'], row.get('date', '')
        history = {h['date']: h.get('close') for h in row.get('history', [])
                   if h.get('date') and h['date'] <= date}
        previous = [d for d in history if d < date]
        change = '漲跌幅無資料'
        if history.get(date) == price and previous:
            close = history[max(previous)]
            if isinstance(close, (int, float)) and math.isfinite(close) and close > 0:
                change = f'{(price / close - 1) * 100:+.2f}%'
        lines.append(f"{row.get('name', symbol)}（{symbol}）｜{row.get('currency', '')} {price:.2f}｜{change}｜{row['rating']['grade']}｜{date}")
    if not symbols:
        lines.append('目前沒有追蹤標的。')
    lines.append('行情日期依各標的列示；規則評級非報酬預測。')
    return '\n'.join(lines)


def run(now=None):
    now = now or local_now()
    day = now.date()
    if (now.hour, now.minute) < (18, 17):
        return {'status': 'outside_send_window'}
    init_db()
    if not is_session(day):
        return {'status': 'closed', 'date': str(day)}
    with leased('watch_digest:worker', 300) as owned:
        if not owned:
            return {'status': 'busy'}
        users = [u for u in subscribed() if can_use_personal(u)
                 and assistant.preferences(u)['daily_brief']]
        sent = skipped = failed = 0
        remaining = None
        for user in users:
            key = f'watch_digest:outbox:{day}:{user}'
            state = get(key) or {}
            if state.get('messages') and all(m.get('sent') for m in state['messages']):
                skipped += 1
                continue
            try:
                if remaining is None:
                    remaining = quota()
                before = remaining
                texts = [] if state else [report(user, day, watches(user))]
                remaining = deliver(user, key, texts, False, remaining)
                sent += before - remaining
            except Exception:
                # Never include subscriber identifiers or credentials in logs.
                failed += 1
        result = {'status': 'partial' if failed else 'finished', 'date': str(day),
                  'subscribers': len(users), 'messages_sent': sent,
                  'already_sent': skipped, 'failed': failed}
        print(result)
        if failed:
            raise RuntimeError('Some daily watch reports were not confirmed')
        return result


if __name__ == '__main__':
    print(run())
