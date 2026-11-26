"""Opt-in mounting of the shadow-only Agent Manager."""
import os
import logging

def mount_agent_manager(app):
    if os.getenv("AGENT_MANAGER_ENABLED") != "1":
        return False
    try:
        from app.api.agent_manager import router
        app.include_router(router)
    except Exception:
        logging.getLogger(__name__).warning("Optional Agent Manager unavailable")
        return False
    return True
