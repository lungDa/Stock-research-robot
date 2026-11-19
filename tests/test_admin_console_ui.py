"""Administrator console renders only for authenticated highest administrator."""
from pathlib import Path
from streamlit.testing.v1 import AppTest

def test_admin_console_hidden_from_public_and_regular_users():
    source = (Path(__file__).parents[1] / "app/day_trader/admin_console_ui.py").read_text()
    assert "if not personal or not is_admin:" in source
    assert '"/admin/ai-limits/"' in source
    assert '"/admin/security/revoke-other-devices"' in source
    assert '"PUT"' in source
    assert "v25_quota_loaded_user" in source

def test_streamlit_mounts_admin_console():
    source = (Path(__file__).parents[1] / "streamlit_app.py").read_text()
    assert "render_admin_console(api, personal, bool(st.session_state.get('is_admin')))" in source


def test_quota_save_requires_correct_scope_in_ui():
    for scope,authorized,disabled in [('ai_limits',True,False),('ai_limits',False,True),('security_settings',True,True)]:
        source=f'''
from app.day_trader.admin_console_ui import render_admin_console
def api(method,path,**kwargs):
    if path=='/admin/role-policy':return {{'mode':'single_superadmin'}}
    if path=='/admin/stepup/status':return {{'authorized':{authorized!r},'scope':{scope!r}}}
    raise AssertionError('unexpected API call')
render_admin_console(api,True,True)
'''
        app=AppTest.from_string(source)
        user='U'+'a'*32
        app.session_state['v25_quota_user']=user
        app.session_state['v25_quota_loaded_user']=user
        app.session_state['v25_quota_loaded']={'normal_daily_limit':0,'emergency_daily_limit':0}
        app.run()
        assert not app.exception
        save=next(b for b in app.button if b.label.startswith('儲存額度'))
        assert save.disabled is disabled
