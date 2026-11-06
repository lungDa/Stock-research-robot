# 驗證紀錄

2026-11-06

- 離線pytest測試：18項（行情/LINE均使用模擬資料，不發送真實通知）。
- Streamlit AppTest：登入頁與已登入三分頁均可載入。
- Python compileall：通過。
- pip check：無相依衝突。
- 本環境Python 3.12；部署設定使用Python 3.11，GitHub CI會執行其相容性測試。
- 真實LINE、Render、Streamlit Cloud、外部PostgreSQL與行情來源未完成端到端驗收，需填入使用者帳號設定後進行。
- FastAPI測試工具顯示一項Starlette/httpx棄用警告，不影響本次測試結果。

## 驗證環境套件版本

- fastapi: 0.162.0
- yfinance: 0.2.66
- streamlit: 1.67.0
- sqlalchemy: 2.1.8
- pandas: 2.2.3
- requests: 2.34.2
- pytest: 9.2.0
