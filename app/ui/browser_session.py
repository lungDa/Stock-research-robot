"""Browser-session token bridge. Never stores credentials in persistent localStorage."""
from pathlib import Path
import streamlit.components.v1 as components

_bridge = components.declare_component(
    "lighthouse_browser_session", path=str(Path(__file__).parent / "browser_session_frontend")
)

def browser_session(command="read", token=None, key="browser_session"):
    return _bridge(command=command, token=token, key=key, default={"pending": True})
