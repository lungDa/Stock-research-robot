"""Build hypothetical close-based swing actions from a verified risk archive."""
from datetime import date, datetime, time
from math import isfinite
import re

import pandas as pd

from app.db import get_many
from app.services.defensive_model import HOLDING_SESSIONS, LOOKBACK_YEARS, backtest
from app.services.defensive_notifications import RISK_SNAPSHOT
from app.services.defensive_research import market_context
from app.services.freshness import TAIPEI

LABELS = {'buy': '建議買進', 'hold': '持續持有', 'watch': '觀望',
          'reduce': '建議減碼', 'exit': '建議退場'}


def swing_action(close, ma20, ma60, risk, holding):
    if any(not isfinite(value) for value in (close, ma20, ma60)):
        return 'watch'
    if holding:
        if close < ma60:
            return 'exit'
        if close < ma20 or risk == 4:
            return 'reduce'
        return 'hold'
    if risk in (2, 3) and close > ma20 > ma60:
        return 'buy'
    return 'watch'


def report(symbol, now, *, holding=False):
    if not re.fullmatch(r'\d{4,6}[A-Z]?\.(TW|TWO)', symbol):
        raise ValueError('expected a Taiwan stock symbol with exchange suffix')
    if now.tzinfo is None:
        raise ValueError('timezone-aware clock required')
    docs, end, closes, _ = market_context(now, symbol)
    if end is None:
        return {'state': 'calendar_missing', 'symbol': symbol}
    history = docs.get('defensive:adjusted:' + symbol, {})
    if not history.get('rows'):
        return {'state': 'stock_history_missing', 'symbol': symbol}
    days = closes.strftime('%Y-%m-%d')
    bars = {row['date']: row for row in history['rows']}
    prices = pd.Series({day: row['close'] for day, row in bars.items()}, dtype=float).reindex(days)
    ma20 = prices.rolling(20).mean()
    ma60 = prices.rolling(60).mean()
    keys = [f'{RISK_SNAPSHOT}:session:{day}' for day in days]
    signals = {}
    management = {}
    levels = {}
    for offset in range(0, len(keys), 80):
        observed = get_many(keys[offset:offset + 80])
        for key, risk in observed.items():
            day = key.rsplit(':', 1)[-1]
            level = risk.get('level')
            if (risk.get('verified') is not True or risk.get('session_date') != day
                    or type(level) is not int or not 0 <= level <= 4):
                continue
            try:
                stamp = datetime.fromisoformat(risk['observed_at'])
                if stamp.tzinfo is None:
                    continue
                stamp = stamp.astimezone(TAIPEI)
            except (KeyError, ValueError, TypeError):
                continue
            if stamp.date().isoformat() != day or stamp.time() < time(13, 30) or stamp > now:
                continue
            levels[day] = level
            action = swing_action(prices[day], ma20[day], ma60[day], level, holding=False)
            management[stamp] = swing_action(prices[day], ma20[day], ma60[day], level, holding=True)
            if action == 'buy':
                signals[stamp] = {'action': action, 'level': level, 'benchmark': 'combined'}

    opens = pd.DatetimeIndex([datetime.combine(date.fromisoformat(day), time(9), TAIPEI)
                              for day in days])
    opening_prices = pd.Series([bars.get(day, {}).get('open') for day in days], index=opens, dtype=float)
    # Keep the full exchange index. Missing bars suppress affected trades, not sessions.
    def simulate(position_signals):
        return {str(years): {str(duration): backtest(
            opening_prices, signals, closes[-1], years, duration,
            allow_missing_opens=True, management=position_signals,
        ) for duration in HOLDING_SESSIONS} for years in LOOKBACK_YEARS}

    today = str(end)
    action = (swing_action(prices[today], ma20[today], ma60[today], levels.get(today), holding)
              if today in levels else 'watch')
    return {
        'state': 'evaluated', 'symbol': symbol, 'as_of': today,
        'action': action, 'label': LABELS[action], 'risk_level': levels.get(today),
        'verified_risk_sessions': len(levels), 'entry_signals': len(signals),
        'backtests': simulate(None), 'managed_backtests': simulate(management),
        'limitations': [
            '僅採本系統曾保存的已驗證收盤風險，早期日期缺檔時不產生歷史訊號。',
            '持倉管理模式首次減碼賣出原持倉 50%，剩餘部位依退場訊號或持有期出場。進場規則使用五基準綜合風險。',
            '使用資料源目前提供的還原日線，未核對歷史版本修訂或逐日財報公布時點。',
        ],
    }
