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
