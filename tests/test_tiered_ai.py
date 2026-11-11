from app.day_trader.tiered_ai import build_tiered_plan,quantitative_lookup

def test_top_ten_deduplicates_four_modes():
    rows=[{"symbol":str(i),"fundamental_score":100-i,
           "technical_score":100-i,"fundamental_complete":True,
           "technical_complete":True} for i in range(25)]
    plan=build_tiered_plan(rows)
    assert len(plan["ai_symbols"])==10
    assert len(set(plan["ai_symbols"]))==10
    assert plan["quantitative_universe_size"]==25
    assert plan["ai_execution_status"]=="NOT_STARTED"
    assert quantitative_lookup(rows,"20")["ai_status"]=="NOT_REQUESTED"

def test_cap_and_missing_scores():
    rows=[{"symbol":"A","fundamental_score":90,"fundamental_complete":True,
           "technical_complete":False},
          {"symbol":"B","technical_score":80,"technical_complete":True,
           "fundamental_complete":False}]
    plan=build_tiered_plan(rows,ai_limit=1)
    assert len(plan["ai_symbols"])==1
    assert plan["rankings"]["combined"]==[]
    assert quantitative_lookup(rows,"A")["technical_score"] is None

def test_stale_not_selected():
    rows=[{"symbol":"A","fundamental_score":99,"technical_score":99,
           "fundamental_complete":True,"technical_complete":True,"data_stale":True}]
    assert build_tiered_plan(rows)["ai_symbols"]==[]
