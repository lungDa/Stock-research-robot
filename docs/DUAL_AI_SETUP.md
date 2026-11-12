# 雙 AI 研究解讀：Gemini 主用／OpenAI 備援

- `app/day_trader/dual_ai.py::review` 預設 `enabled=False`，不會自動產生費用。
- 開啟後先嘗試 Gemini；無金鑰、逾時、錯誤或空回應則改用 OpenAI。
- 可在程式呼叫時交換主備順序，但尚未提供 UI 設定。
- 在部署服務的秘密環境變數設定 `GEMINI_API_KEY`、`OPENAI_API_KEY`，可選 `GEMINI_MODEL`、`OPENAI_MODEL`。切勿將金鑰寫入 GitHub。
- 僅傳送股票代號、技術指標、基本面分數與研究訊號；不傳使用者帳號、持倉、密碼或憑證。
- 模型回覆只作為研究說明，**不會更改量化分數、不會直接下單**。
- 本次新增雙服務適配器與測試，**尚未**整合四榜排程、Streamlit 顯示或 LINE AI 文案。
- 正式啟用前需設定模型成本預算、速率限制、輸出審查及回測。
