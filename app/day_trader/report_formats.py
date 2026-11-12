"""Format verified stock research for LINE (brief) and Streamlit (detail).

No fabricated indicators; AI commentary is optional and clearly attributed.
"""
from datetime import datetime

def _value(value):
    return "資料不足" if value is None else str(value)

def _validate(report):
    if not isinstance(report,dict) or not isinstance(report.get("symbol"),str) or not report["symbol"].strip():
        raise ValueError("report must include symbol")
    technical=report.get("technical")
    if not isinstance(technical,dict):
        technical={}
    return technical

def line_brief(report, ai=None):
    tech=_validate(report)
    symbol=report["symbol"]
    lines=["股海燈塔｜"+symbol,"技術分數："+_value(tech.get("score"))+"/100",
           "基本面分數："+_value(report.get("fundamental_score")),
           "資料時間："+_value(report.get("as_of"))]
    components=tech.get("components") or {}
    if components:
        lines.append("趨勢／動能／量能："+"/".join(_value(components.get(k)) for k in ("trend","momentum","volume")))
    if ai and ai.get("status")=="OK" and ai.get("commentary"):
        lines.append("AI解讀（"+str(ai.get("provider","unknown"))+"）："+str(ai["commentary"])[:180])
    else:
        lines.append("AI解讀：尚未提供；僅顯示已驗證量化資料")
    lines.append("僅供研究，非投資建議；未啟用實盤下單。")
    return "\n".join(lines)[:900]

def streamlit_detail(report, ai=None):
    tech=_validate(report)
    details={"symbol":report["symbol"],"as_of":report.get("as_of"),
             "technical_score":tech.get("score"),
             "technical_complete":tech.get("complete",False),
             "technical_components":tech.get("components") or {},
             "indicators":{k:tech.get(k) for k in ("ma20","ma60","rsi14","relative_volume")},
             "fundamental_score":report.get("fundamental_score"),
             "technical_reason":tech.get("reason") or tech.get("note"),
             "ai_status":(ai or {}).get("status","NOT_CONFIGURED"),
             "ai_provider":(ai or {}).get("provider"),
             "ai_commentary":(ai or {}).get("commentary") if (ai or {}).get("status")=="OK" else None,
             "risk_note":"資料缺漏不補造；量化分數不受AI回覆影響；非交易指令。"}
    return details
