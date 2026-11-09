# 股海燈塔：新台股財報備援來源小量驗證

此包只驗證DataSinking免費財報來源，不宣稱已自動補齊EPS、ROE或配息率。DataSinking提供Markdown財報全文，不是現成TTM數值API；須先確認來源涵蓋、財報期間、單位與表格內容，才能安全接進評分。

## 取得免費Key

1. 開啟 https://datasink.ing/pricing ，選Free區塊的Get Free。
2. 依網站流程取得免費API Key；不選Yearly或付費結帳。
3. GitHub lungDa/Stock-research-robot → Settings → Secrets and variables → Actions → Secrets → New repository secret。
4. Name填DATASINK_API_KEY，Secret貼上你的免費Key。不要貼到聊天、公開檔案或Repository Variable。

供應商目前方案頁標示Free為$0/forever，個人輕量使用，每7天每Key最多8191份文件，另有所有免費使用者共用池。額度以文件數而非單純請求數計算，資料與方案仍以供應商當時公告為準。

## 安裝與執行

將包內 scripts/check_tw_report_backup.py、.github/workflows/report-backup-check.yml 與 tests/test_report_backup_check.py 依原路徑上傳GitHub main。保留原本其他檔案，.github開頭有點。

Actions → Check Taiwan report backup → Run workflow，symbol先保留2330.TW。

此第一階段檢查限四位數上市代號.TW；上櫃、其他市場及全面輪掃尚未接入，不能由這次成功推論所有台股都有資料。

展開Validate one public report：
- 成功會列出公開的公司、報告期間、文件類型、內容大小及是否出現EPS／淨利／權益／股利支出等關鍵字。
- numeric_values_verified固定為false。關鍵字出現不代表數字已正確抽取，更不代表已算成TTM。
- 不輸出Key、完整請求URL或財報全文。
- 若失敗只顯示錯誤類別；表示權限、資料格式、涵蓋、網路或大小上限等仍待確認，請勿反覆重跑。

完成後可提供這個步驟的結果，據以確認能否接EPS／ROE報表解析。Key不用傳給任何人。

## 預算與界線

- 手動執行，沒有新增定時排程。
- 最多兩次HTTP請求：1筆目錄＋1份財報。
- 目錄最多64KiB、財報最多512KiB；各6秒串流軟預算，步驟硬限制1分鐘，整個工作最多4分鐘。
- 財報超過大小預算就停止，不把截斷內容當完整報表。
- 不寫資料庫，不變更現有數字、不發LINE訊息、不啟用付費方案。
- REST依官方文件以apikey參數認證；程式不記錄包含Key的URL或原始網路例外。

## 為何先驗證

已檢查的其他候選：FinLab免費台股資料只到較舊期間；TWMD免費層不含財報三表。它們目前不適合拿來承諾最新TTM三項都能補齊。

DataSinking的官方文件列台股財報目錄與全文查詢，但這次尚未使用你的Key做正式連線驗證，也尚未確認全部台股的最新期涵蓋。

本機5項測試通過：請求數與大小預算、公司／期間核對、錯誤代號拒收、來源文字不直接當數值、例外不洩漏Key。

官方資料：
https://datasink.ing/pricing
https://datasink.ing/zh-tw/docs
https://studio.finlab.finance/docs/reference/data
https://twmarketdata.com/zh-TW/pricing
