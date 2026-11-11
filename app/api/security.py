import hmac
from fastapi import Header,HTTPException,Depends
from app.config import settings

def current_user(authorization:str=Header(default='')):
    token=authorization.removeprefix('Bearer ')
    if not authorization.startswith('Bearer '): raise HTTPException(401,'請先LINE登入並完成個人密碼驗證')
    if not settings.login_channel_id:
        for key,user in settings.users.items():
            if hmac.compare_digest(token,key): return user
    from app.api.line_login import digest
    from app.db import get
    from app.services.accounts import is_member
    import time
    session=get('auth:session:'+digest(token),{})
    member=get('member:'+session.get('user',''),{})
    if (session.get('expires',0)>time.time() and session.get('stage')=='active' and
        session.get('password_version')==member.get('password_version') and not member.get('password_change_required',True) and is_member(session.get('user',''))):
        if session.get('session_id'):
            from app.api.device_sessions import permitted
            if not permitted(session['session_id']):raise HTTPException(403,'裝置登入已撤銷')
        return session['user']
    raise HTTPException(403,'登入已過期或無效，請重新使用LINE登入')


def is_admin(user):
    import os
    legacy = user in {s.strip() for s in os.getenv('ADMIN_LINE_USER_IDS', '').split(',') if s.strip()}
    if legacy:
        return True
    # Once the one-time LINE OTP binding is complete, the designated
    # lighthouse administrator also inherits all existing admin endpoints.
    from app.day_trader.admin_bootstrap import admin_identity_matches
    return admin_identity_matches(user)


def current_admin(user=Depends(current_user)):
    if not is_admin(user):raise HTTPException(403,'僅管理者可查看系統狀態')
    return user


def current_lighthouse_admin(user=Depends(current_user)):
    """V2.5-only administrator guard. Does not trust legacy ADMIN_LINE_USER_IDS."""
    from app.day_trader.admin_bootstrap import admin_identity_matches
    if not admin_identity_matches(user):
        raise HTTPException(403, '尚未完成最高管理員雙重綁定')
    return user
