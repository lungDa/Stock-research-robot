"""Per-user LINE preferences and transitions for verified defensive risk."""
from app.db import get, put

RISK_SNAPSHOT = 'defensive:risk'


def preference(user):
    return get('defensive:line:preference:' + user, {'enabled': False})


def save_preference(user, enabled):
    value = {'enabled': enabled}
    put('defensive:line:preference:' + user, value)
    return value


def event(level, previous, symbols):
    """Compare to the last accepted alert and prior processed risk level."""
    old_level = previous.get('level', 0)
    alerted = previous.get('alerted_level', 0)
    old_symbols = previous.get('symbols', [])
    if level < 2:
        return 'resolved' if alerted >= 2 else None
    if alerted < 2:
        return 'first'
    if level > old_level:
        return 'escalated'
    if level >= 3 and symbols and (
        symbols[:3] != old_symbols[:3] or len(set(symbols) ^ set(old_symbols)) >= 4
    ):
        return 'ranking_changed'
    return None


def message(kind, level, stamp, items):
    labels = {'resolved': '風險解除', 'first': '首次風險提醒',
              'escalated': '風險升級', 'ranking_changed': '逆勢榜單有重大變動'}
    lines = [f'股海燈塔｜{labels[kind]}', f'風險 Level {level}', f'觀測時間 {stamp}']
    if level >= 3:
        if items:
            lines.append('近 1 年五基準綜合榜（已套用財務與技術篩選）')
            lines.extend(f"{index}. {item['symbol']}｜{item['score']:.1%}"
                         for index, item in enumerate(items, start=1))
        else:
            lines.append('目前沒有可用的當期篩選排名。')
    return '\n'.join(lines)
