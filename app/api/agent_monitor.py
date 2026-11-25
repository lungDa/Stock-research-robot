"""Opt-in authenticated shadow route. Never sends or writes."""
import os
from fastapi import APIRouter, Depends, HTTPException
from app.api.security import current_admin
from app.agents.supervisor import Supervisor

router = APIRouter()

@router.get("/admin/agents/system-monitor")
def system_monitor(user=Depends(current_admin)):
    if os.getenv("AGENT_MONITOR_ENABLED")!="1":
        raise HTTPException(503,"Agent monitor disabled")
    return Supervisor(enabled=True).monitor(is_admin=True)
