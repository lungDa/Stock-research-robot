"""LINE身分作個人資料主鍵；每人獨立加鹽密碼雜湊。"""
import hashlib,hmac,secrets,json
from app.db import get,put,Session,Document
from app.config import settings
from sqlalchemy import select

def password_hash(password):
    salt=secrets.token_bytes(16)
    key=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1)
    return 'scrypt$'+salt.hex()+'$'+key.hex()

def password_matches(password,encoded):
    try:
        _,salt,expected=encoded.split('$')
        key=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1)
        return hmac.compare_digest(key.hex(),expected)
    except (ValueError,TypeError,AttributeError):return False

def is_member(user):
    record=get('member:'+user)
    if record is not None:return bool(record.get('active'))
    return user in settings.users.values()

def register(user,name):
    record=get('member:'+user)
    if record is None:
        record={'active':True,'password_hash':None,'password_change_required':True,'password_version':0,'activation_pending':True}
        # 首次建檔不覆蓋同時登入已建立的帳戶。
        from app.db import claim
        claim('member:'+user,{**record,'name':str(name)[:100]})
        record=get('member:'+user)
    if not record.get('active'):raise PermissionError('帳戶已停用')

def member_users():
    with Session() as s:
        accounts={r.key[7:]:json.loads(r.payload) for r in s.scalars(select(Document).where(Document.key.like('member:%')))}
    users=set(settings.users.values())|set(accounts)
    return sorted(u for u in users if accounts.get(u,{'active':True}).get('active') and not accounts.get(u,{}).get('password_change_required',False))

def can_use_personal(user):
    record=get('member:'+user)
    if record is not None:return bool(record.get('active')) and not record.get('password_change_required',True)
    return user in settings.users.values()
