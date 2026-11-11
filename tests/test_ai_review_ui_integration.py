"""Static integration guard: stock query mounts AI panel; no anonymous AI calls."""
from pathlib import Path

def test_ai_review_is_mounted_on_stock_query():
    source=Path("streamlit_app.py").read_text(encoding="utf-8")
    assert "render_ai_review(api, personal, d)" in source
    assert source.index("render_ai_review(api, personal, d)") > source.index("d=st.session_state.get('result')")

def test_ai_review_requires_login_and_explicit_click():
    source=Path("app/day_trader/ai_review_ui.py").read_text(encoding="utf-8")
    assert "if not personal:" in source
    assert 'api("GET", "/ai/usage")' in source
    assert 'if st.button("執行 AI 解讀／查看今日結果"' in source
    assert 'api("POST", "/ai/review", json={"symbol": symbol, "kind": kind})' in source
    assert 'get("date", "")' in source
