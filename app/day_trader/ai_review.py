"""AI review is optional, untrusted narrative; cannot overwrite quantitative ranks."""
from app.day_trader.technical import score as technical_score

def prepare_review(symbol, bars, fundamental_score=None):
    technical=technical_score(bars)
    return {"symbol":symbol,"technical":technical,
            "fundamental_score":fundamental_score,
            "ai_status":"NOT_CONFIGURED",
            "ai_commentary":None,
            "score_mutable_by_ai":False,
            "order_execution_allowed":False,
            "review_guidance":"AI僅可解讀已驗證的數值與風險，不可補造缺漏資料或修改量化分數。"}
