from app.agents.system_monitor import SystemMonitor

class Registry:
    """Fixed trusted implementations; no dynamic imports or user plugins."""
    def resolve(self, name):
        if name == "system_monitor":
            return SystemMonitor()
        return None
