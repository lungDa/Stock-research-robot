# 股海燈塔：Render＋Streamlit 雙服務檢查

每4小時檢查一次：先檢查Render，再以真正瀏覽器開啟Streamlit。沿用原本的 .github/workflows/streamlit-visit.yml，覆蓋六小時版，避免同時執行兩套排程。

## 上傳與設定

1. 把包內3個程式／工作流程檔案，依照原路徑上傳 lungDa/Stock-research-robot 的 main 分支：
   - .github/workflows/streamlit-visit.yml（覆蓋原檔；名稱開頭有一個點）
   - scripts/visit_streamlit.py（覆蓋原檔）
   - scripts/check_render_health.py（新增）
2. GitHub → Settings → Secrets and variables → Actions → Variables。
   - PUBLIC_APP_URL：填完整的Streamlit HTTPS首頁網址，不含登入碼、查詢參數；若之前已填，不必重建。
   - RENDER_HEALTH_URL：可不填。預設為 https://stock-research-robot.onrender.com/health 。只有換Render服務時才需設定。
   - 以上是Repository variables，不是Secrets，也不是Render環境變數。
3. Actions → Check Render and Streamlit (best effort) → Run workflow，選main，先手動執行一次。
4. 展開工作步驟，確認同時出現：
   - Check Render health：Confirmed Render /health: HTTP 200 and status=ok.
   - Visit public app and request wake-up if shown：Confirmed public app heading rendered.
   - 整個工作為綠色成功，才代表當次兩項都通過。

若還有其他舊的保活工作流程，請停用重複排程；本包只會覆蓋streamlit-visit.yml，不會自動刪除其他檔案。

## 成功判定與預算

- Render：單次請求等待最多65秒，回應最多16 KiB，必須HTTP 200且JSON的status為ok。不連續重試。
- Streamlit：瀏覽器實際載入公開首頁；看到官方休眠喚醒按鈕時，最多點一次。
- 「股海燈塔」標題必須可見，等待8秒後仍可見，才算成功。HTTP 200或只顯示休眠頁，都不算成功。
- Render失敗時仍會執行網頁檢查，方便分辨是哪個服務有問題；任何一項失敗，整個工作仍顯示失敗。
- 每個檢查步驟有2分鐘硬限制；瀏覽器載入與輪詢合計使用100秒內部預算，確認標題後另等待8秒；整個工作最多6分鐘。
- 排程為UTC 43 */4 * * *，台灣每日00:43、04:43、08:43、12:43、16:43、20:43，正常每天6次。
- 使用GitHub runner既有Chrome；只安裝Playwright控制套件，不另外下載瀏覽器。

這是免費方案的盡力檢查／喚醒，不能保證24小時在線。GitHub可能延遲或停用排程，平台也可能不將自動瀏覽視為有效使用。每4小時檢查也無法避免Render在兩次檢查之間休眠；這個排程主要用來定時檢查兩項服務及維持Streamlit活動。

不登入、不查股票、不操作個人資料、不發LINE訊息；不修改既有盤後掃描或LINE推播排程。仍會產生少量公開首頁及健康檢查流量。

## 已完成驗證

已通過10項本機模擬測試：URL檢查、健康JSON判定、回應大小限制、可見標題、休眠喚醒、缺少標題、標題消失、內嵌頁面辨識、隱藏內嵌頁面排除及瀏覽器關閉。
尚未在你的GitHub runner與正式網站完成端到端測試；上傳後以手動執行結果為準。

## 內嵌頁面辨識修正

已在公開網站確認：Streamlit外層頁面會內嵌實際應用程式。舊版只尋找外層標題，可能在首頁正常時仍逾時；本版會檢查可見內嵌頁面中的標題及喚醒按鈕。仍維持原本時間上限，不以網頁標題或HTTP 200代替實際內容。

若上一版已安裝，只要覆蓋 scripts/visit_streamlit.py，其他設定與工作流程不用變，再手動Run workflow。修正版尚未在你的GitHub runner執行；本機10項模擬測試已通過。
