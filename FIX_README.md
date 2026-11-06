# Yahoo限流修正版（2026-11-06）

本次針對日誌中 ticker.info → YFRateLimitError 的問題修正。

## 安裝

1. 解壓縮本檔。
2. 到 https://github.com/lungDa/Stock-research-robot 根目錄，選 Add file → Upload files。
3. 將解壓縮後的 app 資料夾、streamlit_app.py 拖入上傳區，保留資料夾層級。可一併上傳 tests 資料夾與本說明檔。
4. 檢查變更路徑為 app/providers/market.py、app/services/research.py、streamlit_app.py，然後 Commit changes。
5. 等Render自動部署完成。若未自動部署，選Manual Deploy → Deploy latest commit。Streamlit會同步GitHub變更，必要時Reboot app。
6. 回網頁重新按分析（原畫面的錯誤不會自動變成成功結果）。不要短時間連續重試。

不用更改 main.py、環境變數或資料庫設定。本修正沒有更改workflow。

## 改善內容

- 日線已取得後，基本資料失敗不會丟棄價格、歷史圖表及波段條件。
- 缺少的EPS/ROE/商品種類標記為未知，不補造數值，不判定存股符合。
- 基本資料限流後暫停該端點請求5分鐘；其他基本資料錯誤暫停1分鐘。
- 日線限流直接進入5分鐘冷卻，不在1、2秒後反覆重抓。其他網路錯誤仍有限次退避重試。
- 基本資料不完整的成功結果快取5分鐘；完整結果維持1小時快取。
- 更新失敗時，可顯示72小時內的舊快取；保留原日期、原更新時間並顯示警示，絕不把舊快取當成剛更新。
- 冷卻保存在目前程序記憶體；服務重啟後會重設，不能視為跨程序限流器。

這是降低故障影響，不能解除Yahoo端限流。若日線也遭限流且沒有可用快取，仍會回報行情暫不可用。穩定長期運作需另選授權資料來源與備援，並驗證資料口徑。

## 驗證

24項離線pytest測試通過（原18項＋6項限流/舊快取回歸測試），行情來源與LINE均使用模擬資料。
尚未帶入你的金鑰在Render實際查詢；GitHub寫入回403，未修改遠端程式。部署後需重新驗收2330查詢。
