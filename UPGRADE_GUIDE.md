# 更新與驗收說明

本次更新說明見 `PROGRAM_GAPS_FIXES.md`；新增檔案請一併提交，不能只覆蓋原有檔案。已有 FinMind 分批狀態會自動續跑，無須清空資料庫。

本版包含台股個股財務補強；先閱讀 `TW_FINANCIALS_UPDATE.md`，並在部署後手動執行 **Verify Taiwan annual EPS and ROE source**，確認新官方入口的實際回應。

本次正式環境追查：更新後執行 **Replenish data and clean expired records**；若2330仍缺欄位，執行新增 **Diagnose stock source gaps**，輸入 `2330.TW`，保留該步驟JSON輸出。這個診斷最多6次請求，不寫入資料庫、不發送LINE；請勿貼出憑證。詳細界線見 `TW_RUNTIME_RECOVERY.md`。

PDF逾時修正：完整更新後執行 **Replenish data and clean expired records**。舊版已記錄的暫時性逾時，會有一次套用新策略的機會；拒絕與格式錯誤的冷卻不略過。來源仍可能逾時，本版不保證所有欄位齊全。

近四季EPS更新：完整更新後，執行一次 **Replenish data and clean expired records**，讓損益表補抓最近兩年的EPS；完成後重新分析2330。新版以`eps_schema`記錄遷移，不需清空資料庫。來源有四個連續完整季度時可計算；來源缺季、限流或未更新時仍待補，不能保證首次查詢即齊。

全台股現金股利支出更新：請完整覆蓋新增模組與工作流程。可單獨執行 **Backfill Taiwan cash-dividend totals**，`symbols`留白為全市場輪替、`years`預設5；既有每日四次續補也已接入。不需新增付費資料來源或清空資料庫。正式來源驗收可執行 **Verify Taiwan cash-dividend source**，預設同時核對上市、上櫃及金融股。

## 1. 套用檔案

將 ZIP 解壓縮後，開啟 `Stock-research-robot-main` 資料夾，將裡面的內容覆蓋至原專案同名路徑。不要再在 GitHub 專案內多包一層同名資料夾。

完整保留 `.github/workflows/`；其中新增 `data-refresh.yml`。保留原本的 GitHub Secrets、Render Environment 與 Streamlit Secrets；ZIP 不含你的憑證。

本次新增 `pypdf` 依賴，Render／GitHub worker 更新時會依 requirements 安裝。後端首次啟動會建立 `worker_leases`、`provider_budgets` 兩張小表；既有人員、追蹤、規則與財報表不刪除。

## 2. 檢查設定

1. Render 與 GitHub 的 `DATABASE_URL` 必須指向同一個 PostgreSQL 資料庫，且帳號有建立新表的權限。
2. 若要自動取得台股財報／股利，兩邊皆設定 `FINMIND_TOKEN`。
3. 若使用 SEC 美股財報，兩邊皆設定包含維護者 Email 的 `SEC_USER_AGENT`。
4. Streamlit 的 `API_BASE_URL` 保持指向原 Render API。原本 LINE Login URL、Channel 設定與 Streamlit 網址不改。
5. 管理者功能為選用：先登入網站，在「我的帳戶資訊（管理者設定用）」顯示自己的 LINE 識別碼，再將該值填入 Render `ADMIN_LINE_USER_IDS`。需要多人時用逗號分隔。其他會員不會因為註冊而自動成為管理者。

## 3. 部署順序

1. 提交完整修改到原專案的預設分支。
2. 等待 GitHub Tests；既有 CI 使用 Python 3.11，仍需由實際 CI 驗證。
3. 等待 Render 部署新後端，再重新啟動或重新部署 Streamlit 前端。
4. 先開啟 API `/health` 確認程序存活，再開 `/ready` 確認資料庫能讀取。
5. 在 GitHub Actions 手動執行 **Replenish data and clean expired records**，確認工作結果；之後每日四次排程會續補。
6. 不需要重新綁定 LINE，不需要重新加入追蹤，也不需要為了補資料開啟通知。

## 4. 用 2412 驗收

- 未登入時查詢 2412，確認行情先出現，再看到背景補資料訊息。
- 本批結束後確認頁面自動刷新及完成／仍待補提醒。資料集數可能只有部分到位，請查看逐欄原因。
- 展開「歷年基本面與來源」，核對年度 EPS 的來源、年度、每股單位與官方原文；EPS 的來源可與同年度其他財務欄位不同。
- 再查一次，不應連續重打相同資料；5 分鐘重複安排限制與來源冷卻仍會生效。
- 如舊快取過期，公開查詢在額度內應嘗試刷新；更新失敗會保留原行情日及原更新時間。
- 將必要 ROE／EPS 條件保留，使用缺漏資料標的確認不會因「已有資料100分」就得到「買」。
- 如你是管理者，點選「檢查資料更新狀態」，查看來源是否設定、每日來源用量、冷卻倒數、有效查詢需求、最近工作與抽樣欄位完整率。

## 5. 不要誤判為下載故障的情況

- 上市 EPS PDF 只涵蓋當次報表的歷年範圍；若來源尚未公布最新完整年度，該年度仍會缺漏。
- 上櫃歷史EPS已新增官方年度來源；若目錄、公司識別、期間或單位無法核對，保留舊值並顯示原因。來源沒有涵蓋的年份仍可補登。
- TTM EPS維持嚴格核對：新增可追溯的獲利／加權股數計算，財報內容仍由使用者確認；沒有同股數基準依據就留白。台股期間須為精確12個月、季末結束。
- ETF 年度總費用率與未支援美股的實際發放日期，不會因增加重試而自動出現。
- 年度多因子、TTM 顯示、已發配息 365 天及近一年簡易檢核是不同期間／規則，畫面會明示。
- 只包含財務因子的自訂規則，若行情過舊，也會停止買入分級；財務分數與已知數值仍保留供查看。

## 6. 維護與排程

- `data-refresh.yml`：每天四次續補與清理，另包含上市／上櫃年度EPS與ROE，不發送 LINE。
- `tw-financial-contract.yml`：僅手動執行的新來源契約驗證，不寫資料庫、不發LINE。
- `daily.yml`：保留原盤後掃描與已訂閱通知，另加入一份 EPS 報表的更新機會。
- `annual-data.yml`：保留手動年度更新，另加入 EPS 更新。
- 工作鎖是資料庫層級，涵蓋網站與 GitHub worker；程序中斷後可在鎖逾期後恢復，不必手動清除。
- 過期暫存清理以分類與游標分批執行，不清除會員、個人規則、追蹤清單、年度財報或 EPS 歷史。
- 舊 `annual:requested` 清單仍可讀取；新需求改為每個標的一筆紀錄，避免整份清單互相覆寫。

## 7. 官方來源與驗證範圍

上市 EPS 表格來源：<https://www.twse.com.tw/pdf/ch/2412_ch.pdf>，程式依股票代號產生同一固定官方網域的 URL。2026-11-09 透過官方文件核對年度欄位結構與公司識別；本地無法連線下載該 PDF 原始位元組，因此本地二進位解析測試使用合成 Unicode PDF，另以官方數值文字樣本測試年度欄位，不宣稱已通過正式來源端到端下載。

季度 EPS 股數基準說明：<https://finmind.github.io/tutor/TaiwanMarket/Fundamental/>。來源說明 EPS 存放各季原始值，配股／分割追溯調整可能使跨季加總不等於累計 EPS，故保留原本的核對要求。

部署後官方 PDF 若有格式變動，程式會拒收並保留舊值，管理狀態與下載原因會反映未完成，不能將留白當成0。

本次不包含正式服務部署、供應商帳號額度驗證或投資策略回測；測試通過不代表選股能獲利。
