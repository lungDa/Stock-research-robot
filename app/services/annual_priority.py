"""Choose a bounded annual-refresh market batch without starving the universe.

The three-field coverage snapshot is advisory, not proof of investability.
"""
import math

def choose_market_batch(universe, cursor, snapshot, now, limit=12, max_age=36*3600):
    """Return (symbols, number_of_market_cursor_slots_advanced)."""
    market=list(dict.fromkeys(s for s in universe if isinstance(s,str) and s.endswith(('.TW','.TWO'))))
    if not market:
        return [],0
    limit=max(1,min(int(limit),len(market)))
    cursor=int(cursor)%len(market)
    snapshot=snapshot if isinstance(snapshot,dict) else {}
    timestamp=snapshot.get('at')
    valid_age=(type(timestamp) in (int,float) and math.isfinite(timestamp)
               and 0<=now-timestamp<=max_age)
    priority=[]
    if valid_age and snapshot.get('scope') in ('THREE_FIELD_DIAGNOSTIC', 'SIX_FACTOR_PROVISIONAL'):
        market_set=set(market)
        priority=list(dict.fromkeys(
            s for s in snapshot.get('symbols',[]) if isinstance(s,str) and s in market_set))
    # Keep at least half of each run for rotating market coverage.
    priority_limit=min(len(priority),limit//2)
    selected=priority[:priority_limit]
    advanced=0
    # Advance across at least half the market slots, even on overlap.
    market_slots=limit-priority_limit
    for i in range(market_slots):
        s=market[(cursor+i)%len(market)]
        advanced+=1
        if s not in selected:
            selected.append(s)
    # If priority overlaps with rotation, fill remaining capacity from the
    # market rotation; never exceed the configured limit.
    while len(selected)<limit and advanced<len(market):
        s=market[(cursor+advanced)%len(market)]
        advanced+=1
        if s not in selected:
            selected.append(s)
    return selected,advanced
