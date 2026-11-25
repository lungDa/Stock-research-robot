from app.agents.system_monitor import SystemMonitor

class Registry:
    """Fixed trusted implementations; no dynamic imports or user plugins."""
    def resolve(self, name):
        if name == "system_monitor":
            return SystemMonitor()
        if name == "data_auditor":
            from app.agents.data_auditor import DataAuditor
            return DataAuditor()
        if name == "notification":
            from app.agents.notification import NotificationAgent
            return NotificationAgent()
        if name == "recovery":
            from app.agents.recovery import RecoveryAgent
            return RecoveryAgent()
        if name == "research":
            from app.agents.research import ResearchAgent
            return ResearchAgent()
        return None
