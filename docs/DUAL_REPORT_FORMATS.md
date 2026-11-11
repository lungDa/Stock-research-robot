# 雙版本研究報告格式

- LINE：`report_formats.line_brief(report, ai)`，簡要列出股票、技術與基本面分數、量化構成、資料時間，以及可用的 AI 摘要。
- Streamlit：`report_formats.streamlit_detail(report, ai)`，輸出結構化完整數據，供網頁顯示指標明細、量化構成、AI 解讀、資料不足原因與風險。
- AI 缺席或服務失敗時，仍可顯示已驗證的量化結果，**不可假裝 AI 已分析**。
- 本次僅新增格式函式與測試，**尚未串入** Streamlit UI、LINE 排程、實際 AI 呼叫或四榜產製。
- 待辦：整合用戶偏好、報告持久化、字數與成本預算、時間戳、全市場評分與測試。
