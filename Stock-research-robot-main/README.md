# 股海燈塔 — Streamlit / LINE 模組版

這是從原 Discord 股票機器人重新整理的新版專案。main.py 只負責啟動 API；前端、行情、分析、LINE、資料庫和排程各自獨立。新版不啟動 Discord，也沒有自動下單。

## 功能與目前界線

- Streamlit：個人金鑰登入、個股/ETF查詢、歷史收盤圖、存股/波段條件、自選清單、通知開關、市場篩選報告。
- LINE 官方帳號一對一：限定白名單、追蹤管理、已快取行情查詢、選股摘要、每日通知開關。
- 台股上市 `.TW`、上櫃 `.TWO`、美股與 ETF；四位純數字預設上市，上櫃必須輸入完整尾碼。
- 每位使用者自選清單獨立，最多30檔；每日摘要需主動開啟。
- 規則篩選不是完整估值模型。ETF 沒有使用 EPS / ROE，缺值顯示「缺資料」。尚未加入新聞AI、回測、持倉損益、稅務、費用換匯、獨立條件觸發推播。
- 行情以日線及供應商資料為準，不是即時交易報價。配息率只算當下往前365天的實際配息；不能代表未來收益。
- 免費預設每次輪掃200檔，另優先更新自選；不是每日掃完所有台美股。網頁顯示36小時內的涵蓋率，缺資料不算符合。可調高 `--limit`，但免費執行時間及資料商限流會限制完整度。
- 母體更新包含上市/上櫃股票與ETF、Nasdaq Trader所列美國交易所商品，並非全球或美國OTC完整名單。分類以行情商為準，不明商品不做存股篩選。
- LINE 為確保盡快回覆，只讀快取；沒有資料時請開網頁分析或加入追蹤。若要 LINE 任意新代號即時分析，後續需補上持久化工作佇列與額外結果推播。

## 檔案分工

| 路徑 | 責任 |
|---|---|
| main.py | 啟動 API |
| streamlit_app.py | 網頁介面，透過 API 讀寫，不直接接資料庫 |
| app/config.py | 環境變數及使用者金鑰設定 |
| app/db.py | SQLAlchemy 資料表、文件快取及去重紀錄 |
| app/providers/market.py | 股票代號、Yahoo行情、配息率與重試 |
| app/providers/universe.py | 讀取掃描母體 CSV |
| app/services/analysis.py | 個股/ETF，存股/波段規則 |
| app/services/research.py | 分析流程與1小時快取 |
| app/services/watchlist.py | 個人追蹤及通知偏好 |
| app/channels/line.py | 簽章、Reply、Push與額度查詢 |
| app/channels/commands.py | LINE文字指令及回覆格式 |
| app/api/security.py | 個人金鑰驗證 |
| app/api/server.py | HTTP路由與錯誤隔離 |
| jobs/refresh_universe.py | 更新台美股母體 |
| jobs/scan.py | 有時間上限、可續跑的分批掃描 |
| jobs/notify.py | 每日合併摘要與去重 |
| .github/workflows/daily.yml | 每個平日台灣14:17執行更新、掃描與通知 |
| render.yaml | 免費Render API部署設定 |
| tests/ | 離線模擬測試，不使用真實LINE或行情 |

拆檔改善可維護性；程序被平台停止、記憶體不足、資料庫中斷仍可能停機。掃描在GitHub Actions獨立執行，行情單檔錯誤不會停止其他股票，API查詢錯誤回503，LINE每個事件獨立處理。免費版本維持單一API worker，不把掃描塞進webhook或Streamlit執行緒。

## 1. 本機先跑

使用 Python 3.11（建議建立虛擬環境）：

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

將 `.env.example` 複製成 `.env`。用下列指令替每個親友產生不同的隨機金鑰：

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

設定 `USER_TOKENS_JSON`，例如（請換成真實隨機金鑰及各自的LINE userId）：

```dotenv
USER_TOKENS_JSON={"replace-with-at-least-24-random-characters":"U_REPLACE_ME"}
```

LINE userId 不是電話、暱稱或可搜尋的LINE ID。自己的userId可在LINE Developers中確認；親友的userId需從其加好友/傳訊產生的已驗簽webhook事件，透過受控開發工具確認。此版本不公開回傳未授權者ID，也沒有自助註冊頁。將每人userId配到其個人金鑰後，在Render與Actions同步更新設定；移除金鑰即可撤權，之後需重新部署生效。

兩個終端分別執行：

```bash
python main.py
```

```bash
python -m streamlit run streamlit_app.py
```

開啟 Streamlit 顯示的本機網址，輸入自己的金鑰。最初的 CSV 是9檔示範，不是完整母體。測試排程：

```bash
python -m jobs.scan --limit 9 --seconds 180
python -m pytest -q
```

沒有LINE憑證時可以跑網頁、分析和追蹤；不能真實接收/發送LINE。

## 2. 共用持久化資料庫（部署必要）

Render與GitHub Actions必須使用同一個外部PostgreSQL。可自行選用有免費額度的服務（例如Neon或Supabase），依該服務當下額度、休眠及保留政策為準。本專案不自動建立外部帳號或付費資源。

設定 `DATABASE_URL` 為服務提供的連線字串（建議帶SSL）：

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require
```

本機SQLite僅供單機測試，不能放在免費Render當持久化儲存，也不能讓Actions各自建立SQLite，否則彼此看不到自選資料。首次啟動建立資料表；後續正式變更資料表需另加資料庫遷移，create_all不會修改舊欄位。資料庫由後端專用，不把連線字串提供給親友或公開前端。

## 3. GitHub與Render

1. 建立新分支或新repository，將本專案內容放repository根目錄；先備份原Discord版本。
2. 不要提交 `.env`、個人金鑰、資料庫檔案或Secrets。此版本未替你推送GitHub。
3. Render使用Blueprint讀取 `render.yaml`，或手動建立Python Web Service。Build為 `pip install -r requirements.txt`，Start為 `python main.py`。
4. 設定 `DATABASE_URL`、`LINE_CHANNEL_SECRET`、`LINE_CHANNEL_ACCESS_TOKEN`、`USER_TOKENS_JSON`。
5. 確認 `https://你的服務.onrender.com/health` 回傳ok。健康檢查表示API有回應，不代表LINE、資料庫及行情來源都正常。
6. 保持單一worker。若之後擴成多副本，需加入跨程序分散式鎖、資料商速率限制及通知工作佇列。

免費Render會休眠，LINE第一則訊息可能因冷啟動而無法及時回覆；本架構避免用Render內建計時器承擔每日工作。沒有啟用外部每5分鐘ping，不能承諾24小時即時回覆。若已有監控服務，可監控 `/health`，仍不能替代排程或保證常駐。

## 4. LINE官方帳號

1. 建立官方帳號並啟用Messaging API，取得Channel Secret及Access Token。
2. Webhook URL填入 `https://你的服務.onrender.com/line/webhook`。
3. 開啟Webhook，先Verify；建議開啟Webhook redelivery，關閉官方帳號預設自動回覆以免重複。
4. 使用者加好友、完成白名單設定後測試：`追蹤 2330`、`我的清單`、`通知開啟`。
5. 快取有資料時測試：`查詢 2330`、`存股選股`、`波段選股`。

LINE簽章以原始body驗證，僅允許白名單的一對一文字事件。事件ID去重，發送失敗回503等待平台重送。已用過的reply token無法保證重新回覆，冷啟動及網路故障仍可能漏回。

主動推播一天每人最多一份合併摘要，執行前查詢官方額度並預留5則；不足就停止，不自動升級。推播使用固定UUID retry key避免同日重送。若程序在預留狀態時被強制終止，採保守策略跳過該日通知，需管理者檢查資料庫 `notification:日期:userId` 紀錄後處理；不承諾exactly-once。超過LINE retry key的有效期間請勿手動重送同一日通知。

## 5. Streamlit Community Cloud

連接同一repository，入口選 `streamlit_app.py`。在Secrets設定：

```toml
API_BASE_URL = "https://你的服務.onrender.com"
```

每位親友各自輸入個人金鑰登入。網址可以開啟，但未登入不會顯示分析或自選資料。不要把所有人的金鑰或資料庫密碼塞進前端Secrets；金鑰由你以私人方式分別提供。此為小型親友版bearer金鑰登入，尚未實作LINE Login / OAuth或登入嘗試速率限制，不適合直接開放大眾。

## 6. 免費排程

在GitHub repository的Settings → Secrets and variables → Actions設定：

- `DATABASE_URL`：與Render相同。
- `USER_TOKENS_JSON`：與Render相同。
- `LINE_CHANNEL_ACCESS_TOKEN`：發送每日摘要用。

啟用Actions，在default branch上執行Daily scan and digest → Run workflow測試。預設平日台灣14:17產生一份台美合併報告；美股使用當時最近可得日線。市場休市時可能仍是前一交易日，報告會保留行情日期，尚未加入交易所行事曆跳日。

母體更新失敗會讓workflow失敗並停止後續通知，不會默默換成示範清單。掃描按資料庫cursor輪流處理母體，自選優先；單檔取得失敗列入失敗清單，不使其他檔停止。一次掃描預算900秒，工作總預算25分鐘。可手動再次執行接續輪掃，但需自行留意Actions免費額度。

GitHub定時工作可能延遲，公開repo長期無活動可能停用排程；私有repo有執行分鐘額度。此版本不是每日掃完全部市場的保證，也未提供盤中即時監控。新增條件通知時應先處理200則額度、訊號從未符合轉為符合的狀態與冷卻時間。

## 資料與運作限制

- Yahoo資料可能缺漏、延遲或限流，ETF費用率欄位尤其可能沒有，這時標記缺資料，不錯判為符合。
- 股價、配息及EPS可能因幣別與供應商口徑而不一致，跨市場不可直接比較絕對EPS；配息率尚未處理稅務、特殊配息、ADR換算。
- 技術均線採還原收盤價；圖表顯示未還原收盤價。波段條件是趨勢篩選，尚無停損/部位配置或績效驗證。
- 快取與去重紀錄在資料庫持久化；目前沒有定期清理事件紀錄，長期使用需加入保留政策及備份。
- 目前自動測試使用SQLite、模擬HTTP與行情；真實PostgreSQL、Yahoo、交易所母體來源、Render、Streamlit Cloud與LINE仍需帶入帳號設定後驗收。

## 官方文件

- Render免費限制：https://render.com/docs/free
- LINE簽章：https://developers.line.biz/en/docs/messaging-api/verify-webhook-signature/
- LINE計費：https://developers.line.biz/en/docs/messaging-api/pricing/
- GitHub排程：https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- Streamlit Secrets：https://docs.streamlit.io/deploy/concepts/secrets
