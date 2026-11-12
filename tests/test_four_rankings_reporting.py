from app.day_trader.reporting import summary

def test_missing_report_does_not_send():
    assert summary({}) is None
    assert summary({"rankings":{}}) is None

def test_empty_lists_report_data_gap_not_fake_top_ten():
    text=summary({"as_of":"2026-11-11","rankings":{}})
    assert text.count("資料不足，暫不排名")==4
    assert "研究用途" in text
