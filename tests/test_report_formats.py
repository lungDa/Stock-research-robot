from app.day_trader.report_formats import line_brief,streamlit_detail
import pytest

def test_brief_and_detail_share_same_scores():
    report={"symbol":"2330.TW","as_of":"2026-11-11","fundamental_score":80,
            "technical":{"complete":True,"score":70,"components":{"trend":40,"momentum":15,"volume":15},
                         "ma20":100,"ma60":98,"rsi14":58,"relative_volume":1.2}}
    ai={"status":"OK","provider":"gemini","commentary":"趨勢向上，注意回撤風險"}
    brief=line_brief(report,ai)
    detail=streamlit_detail(report,ai)
    assert "70/100" in brief
    assert detail["technical_score"]==70
    assert detail["ai_commentary"] in brief
    assert detail["indicators"]["rsi14"]==58

def test_missing_data_is_not_fabricated():
    report={"symbol":"2412","technical":{"complete":False,"score":None}}
    assert "資料不足" in line_brief(report)
    assert streamlit_detail(report)["technical_score"] is None

def test_invalid_symbol_rejected():
    with pytest.raises(ValueError):line_brief({"technical":{}})
