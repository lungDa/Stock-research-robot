"""Streamlit V2.5 personal device management and administrator step-up UI."""
import streamlit as st

SCOPES = {
    "ai_limits": "AI 額度管理",
    "role_management": "管理員權限管理",
    "security_settings": "系統安全設定",
}

def render_security_center(api, personal, is_admin):
    if not personal:
        return
    with st.expander("🔐 登入裝置與安全管理", expanded=False):
        st.caption("登入裝置可同時使用；撤銷指定工作階段後，該裝置的登入與管理授權立即失效。")
        if st.button("更新裝置清單", key="v25_devices_refresh"):
            st.session_state.pop("v25_devices", None)
        if "v25_devices" not in st.session_state:
            result = api("GET", "/auth/devices")
            if result is not None:
                st.session_state.v25_devices = result.get("devices", [])
        for device in st.session_state.get("v25_devices", []):
            from datetime import datetime, timezone
            created = datetime.fromtimestamp(device["created_at"], timezone.utc).astimezone(
                __import__("zoneinfo").ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M")
            label = ("目前裝置" if device.get("current") else "其他裝置")
            if device.get("revoked"):
                label += "（已登出）"
            left, right = st.columns([4, 1])
            left.write(f"**{label}**｜登入：{created}")
            if not device.get("revoked") and right.button("登出", key="v25_revoke_" + device["session_id"]):
                result = api("POST", "/auth/devices/" + device["session_id"] + "/revoke")
                if result is not None:
                    st.session_state.pop("v25_devices", None)
                    if device.get("current"):
                        st.session_state.clear()
                    st.rerun()
        if st.button("登出其他所有裝置", key="v25_revoke_others"):
            if api("POST", "/auth/devices/revoke-others") is not None:
                st.session_state.pop("v25_devices", None)
                st.success("已撤銷其他裝置的登入工作階段")
                st.rerun()
        if not is_admin:
            return
        st.divider()
        st.subheader("最高管理員｜重要操作授權")
        status = api("GET", "/admin/stepup/status")
        if status is None:
            st.info("請先完成最高管理員初始化，才能使用重要操作授權。")
            return
        if status.get("authorized"):
            scope_name = SCOPES.get(status.get("scope"), "未知操作")
            st.success(f"已授權：{scope_name}｜剩餘約 {status.get('expires_in', 0)} 秒")
        else:
            st.info("目前沒有有效的管理操作授權。")
        scope = st.selectbox("選擇需要授權的操作", list(SCOPES),
                             format_func=lambda value: SCOPES[value], key="v25_stepup_scope")
        if st.button("發送 LINE 驗證碼", key="v25_stepup_send"):
            if api("POST", "/admin/stepup/otp", json={"scope": scope}) is not None:
                st.success("驗證碼已發送至綁定的 LINE 帳號，5 分鐘內有效。")
        with st.form("v25_stepup_verify_form"):
            code = st.text_input("六位數 LINE 驗證碼", max_chars=6, type="password")
            submit = st.form_submit_button("驗證並取得 10 分鐘授權")
        if submit:
            if len(code) != 6 or not code.isascii() or not code.isdigit():
                st.error("請輸入六位半形數字")
            elif api("POST", "/admin/stepup/verify", json={"scope": scope, "code": code}) is not None:
                st.success("驗證成功，已取得指定操作類別的 10 分鐘授權。")
                st.rerun()
        st.caption("高風險操作仍需獨立驗證；介面授權不取代後端敏感 API 的權限檢查。")
