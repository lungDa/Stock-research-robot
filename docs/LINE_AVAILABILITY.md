# LINE 回覆可用性（維持免費方案）

## 後端健康檢查

`.github/workflows/render-health.yml` 獨立檢查 Render，每小時的第 7、17、27、37、47、57 分排程一次，目標間隔 10 分鐘。
這是 GitHub Actions 的盡力排程，可能延遲、漏跑或因長期無活動而停用，不保證全天可用。
合併至 `main` 後排程才會啟用；修改工作流程或檢查腳本時，也會先在 PR 及合併後各驗證一次。

- 僅使用 Python 標準函式庫，單次請求 `/health`；保留 65 秒 socket timeout，允許免費實例喚醒。
- 驗證 HTTP 200 且 JSON 的 `status` 為 `ok`；喚醒 HTML、錯誤狀態、內容過大或逾時均視為失敗，不用假成功掩蓋問題。
- 記錄回應秒數；不呼叫財報下載、行情查詢、資料庫 readiness 或 LINE 發訊端點。
- 既有每四小時的 Streamlit 網頁檢查保留原排程，兩項工作互不等待，也不每十分鐘啟動瀏覽器。
- 不建立付費服務、不更改 Render 方案、不使用 LINE Token。後端存活不代表 Webhook 設定或 LINE 回覆已驗證。

`RENDER_HEALTH_URL` 是選用的 GitHub repository variable；未設定時沿用既有預設 `https://stock-research-robot.onrender.com/health`。
若更換服務，可在 Settings → Secrets and variables → Actions → Variables 修改此變數；只接受 HTTPS 的 `*.onrender.com/health`，不含查詢字串或帳密。

## 驗證及故障追查

1. 在 Actions 開啟 **Check Render backend every 10 minutes (best effort)**，查看最近實際執行時間與回應秒數；必要時用 Run workflow 手動檢查。
2. 到 LINE 官方帳號傳送「功能選單」。只有實際收到回覆才能驗證完整通路。
3. 若健康檢查成功仍無回覆，查看 LINE Developers Webhook 錯誤統計與 Render Logs 中的 `LINE delivery stage=... category=...`。核對 Webhook URL、啟用狀態與授權；勿將 Token 貼到日誌或對話。
4. `/ready` 可供手動確認資料庫；不要用高頻資料查詢替代單純後端檢查。Webhook 目前仍等待指令與回覆完成才回傳成功，因此資料庫／LINE API 延遲仍可能造成逾時。

## 免費額度與限制

Render 免費實例閒置 15 分鐘會休眠；此排程降低閒置機率，無法消除重啟、部署、排程延遲或月額度用完造成的中斷。
Render 每個 workspace 的免費服務共用每月 750 instance hours；持續運行一個服務每月約 720–744 小時，多個服務會共用額度。此變更不升級方案，但會增加實例運行時間，仍須查看既有帳戶額度。

官方說明：

- [Render 免費服務限制](https://render.com/docs/free)
- [GitHub 排程延遲與停用條件](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
