from app.day_trader.ai_quota import prioritise, DAILY_LIMIT

def test_daily_default_and_deduplication():
    rows=[{"symbol":str(i),"best_rank":i+1} for i in range(50)]
    rows.append({"symbol":"0","best_rank":1})
    result=prioritise(rows)
    assert result["daily_limit"]==40
    assert result["selected_count"]==40
    assert result["deferred_count"]==10
    assert len(set(result["selected"]))==40

def test_new_top_ten_precedes_rank():
    rows=[{"symbol":"A","best_rank":1},{"symbol":"B","best_rank":8,"new_top_ten":True}]
    assert prioritise(rows,limit=1)["selected"]==["B"]

def test_deterministic():
    rows=[{"symbol":"B","best_rank":1},{"symbol":"A","best_rank":1}]
    assert prioritise(rows,limit=2)["selected"]==["A","B"]
