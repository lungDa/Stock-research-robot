from app.day_trader.ai_cache import decide_cache

CURRENT={"symbol":"2330","data_complete":True,"data_stale":False,
         "fundamental_score":80,"technical_score":70,"signal":"HOLD","source_revision":"r1"}
CACHED={"symbol":"2330","generated_at":"2026-11-11T08:00:00+08:00",
        "ai_status":"OK","commentary":"趨勢偏強","fundamental_score":80,
        "technical_score":70,"signal":"HOLD","source_revision":"r1"}
NOW="2026-11-11T11:30:00+08:00"

def test_reuse_stable_scores():
    r=decide_cache(CURRENT,CACHED,now=NOW)
    assert r["action"]=="REUSE"
    assert "original_generated_at" in r

def test_refresh_on_signal_or_score_change():
    assert decide_cache({**CURRENT,"signal":"BUY"},CACHED,now=NOW)["action"]=="REFRESH"
    assert decide_cache({**CURRENT,"technical_score":75},CACHED,now=NOW)["action"]=="REFRESH"
    assert decide_cache({**CURRENT,"source_revision":"r2"},CACHED,now=NOW)["action"]=="REFRESH"

def test_missing_data_skips_not_reuses():
    assert decide_cache({**CURRENT,"data_complete":False},CACHED,now=NOW)["action"]=="SKIP"

def test_expired_cache_refreshes():
    assert decide_cache(CURRENT,CACHED,now="2026-11-13T12:00:00+08:00")["action"]=="REFRESH"
