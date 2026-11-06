import os, json
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv()
@dataclass
class Settings:
    database_url: str = os.getenv('DATABASE_URL','sqlite:///./local.db')
    line_secret: str = os.getenv('LINE_CHANNEL_SECRET','')
    line_token: str = os.getenv('LINE_CHANNEL_ACCESS_TOKEN','')
    # {個人存取金鑰: LINE userId}，每個人一把，空設定一律拒絕。
    users_json: str = os.getenv('USER_TOKENS_JSON','{}')
    @property
    def users(self):
        value=json.loads(self.users_json)
        if not isinstance(value,dict) or any(len(k)<24 or not isinstance(v,str) or not v.startswith('U') for k,v in value.items()):
            raise ValueError('USER_TOKENS_JSON 必須為 {至少24字元隨機金鑰: LINE userId}')
        return value
settings=Settings()
