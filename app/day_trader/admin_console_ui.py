"""Single-superadministrator management console.

The API enforces administrator identity and device-scoped LINE OTP; this UI is
only an operator surface and never decides authorization.
"""
import re
import streamlit as st

def render_admin_console(api, personal, is_admin):
    if not personal or not is_admin:
        return
    with st.expander("🛡️ 最高管理員控制中心", expanded=False):
        policy = api("GET", "/admin/role-policy")
        if policy is None:
            st.warning("無法取得管理員制度，請稍後再試。")
            return
        st.info("目前採單一最高管理員制度：不開放新增、委派或轉移管理員權限。")
        quota, security = st.tabs(["AI 額度管理", "系統安全設定"])
        with quota:
            st.caption("修改 AI 額度需先至「登入裝置與安全管理」完成「AI 額度管理」LINE OTP 授權（10 分鐘有效）。")
            target = st.text_input("使用者 LINE ID", key="v25_quota_user", max_chars=33,
                                   placeholder="U 開頭的 33 字元 LINE 使用者 ID")
            valid = bool(re.fullmatch(r"U[0-9a-fA-F]{32}", target.strip()))
            if st.button("查詢目前額度", key="v25_quota_load"):
                if not valid:
                    st.error("請輸入有效的 LINE 使用者 ID。")
                else:
                    result = api("GET", "/admin/ai-limits/" + target.strip())
                    if result is not None:
                        st.session_state.v25_quota_loaded = result
                        st.session_state.v25_quota_loaded_user = target.strip()
            loaded = st.session_state.get("v25_quota_loaded")
            if loaded and st.session_state.get("v25_quota_loaded_user") == target.strip():
                with st.form("v25_quota_form"):
                    normal = st.number_input("每日一般 AI 額度", min_value=0, max_value=100000,
                                             value=int(loaded.get("normal_daily_limit", 0)), step=1)
                    emergency = st.number_input("每日緊急 AI 額度", min_value=0, max_value=100000,
                                                value=int(loaded.get("emergency_daily_limit", 0)), step=1)
                    submit = st.form_submit_button("儲存額度（需要 AI 額度 OTP 授權）")
                if submit:
                    result = api("PUT", "/admin/ai-limits/" + target.strip(),
                                 json={"normal_daily_limit": int(normal),
                                       "emergency_daily_limit": int(emergency)})
                    if result is not None:
                        st.session_state.v25_quota_loaded = result
                        st.success("額度已更新。")
            elif target.strip() and valid:
                st.caption("請先查詢該使用者的目前額度，再進行修改。")
        with security:
            st.caption("此處的撤銷操作需要「系統安全設定」LINE OTP 授權。")
            if st.button("撤銷其他所有裝置（管理員安全操作）", key="v25_admin_revoke_others"):
                result = api("POST", "/admin/security/revoke-other-devices")
                if result is not None:
                    st.session_state.pop("v25_devices", None)
                    st.success(f"已撤銷其他 {result.get('revoked', 0)} 個登入工作階段。")
            st.warning("管理員身分不可透過此介面新增、委派或轉移。")
