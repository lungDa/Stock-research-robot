"""最高管理員首次綁定：只有後端預先指定的 LINE 帳號可看到操作介面。"""
import re
import streamlit as st

def render_admin_bootstrap(api, personal):
    if not personal:
        return
    status = api('GET', '/admin/bootstrap/status')
    if not status or not status.get('designated'):
        return
    st.divider()
    st.subheader('🔐 最高管理員首次綁定')
    if status.get('initialized'):
        st.success('最高管理員 LINE 身分已完成一次性綁定。')
        return
    st.info('此操作只限預先指定的 LINE 帳號。驗證碼將傳送至你的 LINE 官方帳號對話。')
    st.caption('驗證碼有效期限 5 分鐘，最多可嘗試 5 次；請勿分享驗證碼。')
    if st.button('發送 LINE 六位數驗證碼', key='admin_bootstrap_send'):
        result = api('POST', '/admin/bootstrap/otp')
        if result and result.get('sent'):
            st.success('已發送驗證碼，請查看 LINE 官方帳號訊息。')
    with st.form('admin_bootstrap_verify_form'):
        code = st.text_input('六位數驗證碼', max_chars=6, type='password',
                             help='請輸入 LINE 收到的六位數驗證碼')
        submitted = st.form_submit_button('確認最高管理員綁定')
    if submitted:
        if not re.fullmatch(r'[0-9]{6}', code):
            st.error('請輸入六位數字驗證碼。')
        else:
            result = api('POST', '/admin/bootstrap/verify', json={'code': code})
            if result and result.get('initialized'):
                st.success('最高管理員綁定完成。')
                st.rerun()
