from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.day_trader.access_models import AdminBootstrap, UserAILimit, EmergencyAIRequest
from app.db import Base

def test_stage_one_defaults_and_single_admin_row():
    engine=create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(UserAILimit(user="new-user"))
        session.add(AdminBootstrap(id=1,designated_user="owner",designated_line_user_id="line-owner"))
        session.commit()
        limits=session.get(UserAILimit,"new-user")
        admin=session.get(AdminBootstrap,1)
        assert limits.normal_daily_limit==0
        assert limits.emergency_daily_limit==0
        assert admin.initialized is False
