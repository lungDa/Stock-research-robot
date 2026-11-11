# V2.5 第二階段：LINE OTP 管理員初始化（開發分支）

## 本次新增
- `app/day_trader/admin_bootstrap.py`：讀取預先指定的 `ai_admin_bootstrap` 資料，透過既有 LINE 官方帳號推播六位 OTP（有效 300 秒，最多五次錯誤）。
- `POST /admin/bootstrap/otp`：需已完成 LINE 登入與平台密碼驗證；只向預先指定的 LINE ID 發送。
- `POST /admin/bootstrap/verify`：需已登入，驗證 OTP 並透過條件式 SQL UPDATE 將初始化狀態永久設為完成。
- `current_lighthouse_admin`：V2.5 專用的後端權限守衛，只有已完成初始化的雙重綁定身分通過。

## 部署前必要事項
- **必須先由受保護的管理程序指定** `ai_admin_bootstrap` 唯一一筆 `id=1` 的 `designated_user` 與 `designated_line_user_id`，兩者均為已完成 LINE Login 與平台密碼驗證的同一個 LINE User ID。
- 不提供公開的「選擇第一位管理員」入口，避免搶先綁定。
- LINE 官方帳號必須具備向該使用者推播的權限及有效憑證。
- 未預先指定、驗證碼過期、錯誤超過五次或已初始化時，一律拒絕。

## 限制與後續
- 目前沿用既有登入流程；本次沒有修改既有 `/admin/status` 的舊版管理員設定，也沒有把 V2.5 守衛接入未來額度管理端點。
- OTP 的失敗次數由資料庫文件及短期租約協調；正式部署前須完成多 worker 競爭、網路故障、重送、異常中斷等整合測試。
- 尚未提供受保護的管理員預先指定工具、正式初始化 UI、完整稽核、緊急審核及金鑰恢復。
- **本階段已提交 GitHub 開發分支，尚未執行 CI 或部署正式環境。**
