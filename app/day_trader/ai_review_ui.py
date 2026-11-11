"""Personal AI narrative panel for the currently displayed stock quote.

The ordinary quote/score remains free. Only explicit clicks call /ai/review.
"""
import streamlit as st


def render_ai_review(api, personal, quote):
    st.divider()
    st.subheader("🤖 AI 股票分析")
    if not personal:
        st.info("AI 分析需先透過 LINE 登入，並完成個人密碼驗證；一般行情與多因子評分仍可免費查詢。")
        return

    symbol = quote.get("symbol")
    if not symbol:
        return
    usage = api("GET", "/ai/usage")
    if usage is None:
        st.warning("目前無法確認 AI 剩餘額度，暫停送出分析。")
        return

    normal = usage.get("normal") or {}
    emergency = usage.get("emergency") or {}
    left, right = st.columns(2)
    left.metric("一般 AI 今日剩餘", f"{normal.get('remaining', 0)} / {normal.get('limit', 0)}")
    right.metric("緊急 AI 今日剩餘", f"{emergency.get('remaining', 0)} / {emergency.get('limit', 0)}")
    st.caption("同日同類別、同一股票的成功分析可重複查看，不重複扣除；分析失敗不扣額度。緊急額度僅供有權限者使用。")
    kind = st.radio("分析額度類別", ["normal", "emergency"], horizontal=True,
                    format_func=lambda x: "一般" if x == "normal" else "緊急",
                    key="v25_ai_kind")
    day = (normal if kind == "normal" else emergency).get("date", "")
    key = f"v25_ai_result:{day}:{symbol}:{kind}"
    if st.button("執行 AI 解讀／查看今日結果", key="v25_ai_run"):
        with st.spinner("AI 正在解讀已取得的量化訊號…"):
            result = api("POST", "/ai/review", json={"symbol": symbol, "kind": kind})
        if result is not None:
            st.session_state[key] = result
            st.rerun()
    result = st.session_state.get(key)
    if not isinstance(result, dict):
        return
    if result.get("status") == "OK":
        st.success("AI 解讀完成" + ("（沿用今日結果，不重複扣額度）" if result.get("reused") else ""))
        st.write(result.get("commentary") or "未提供文字解讀")
        st.caption(f"AI 來源：{result.get('provider', '未知')}｜AI 文字不改變原有量化評分，也不會執行交易。")
    elif result.get("status") == "UNAVAILABLE":
        st.warning("AI 服務暫時無法完成分析，本次不扣除額度。")
    elif result.get("status") == "QUOTA_PENDING":
        st.info("此股票已有分析進行中，請稍後再試。")
    elif result.get("status") == "RESULT_UNAVAILABLE":
        st.warning("今日分析已記錄，但快取結果暫時無法取得，請稍後再試。")
    else:
        st.warning("AI 分析未完成：" + str(result.get("status", "未知狀態")))
