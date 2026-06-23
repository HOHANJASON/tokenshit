# NexToken Local Backend

NexToken Local 是獨立開發的本機 AI API 管理系統，不依賴 New API 後台。它將客戶網站、管理後台、客戶控制台與 OpenAI 相容 API 放在同一個本機服務中。

## 第一版功能

- OpenAI 相容供應商通道管理
- 上游 API Key 加密保存
- 模型名稱、成本、客戶售價及上下架
- 客戶註冊、登入、餘額與 API Key
- `/v1/models` 與 `/v1/chat/completions`
- 串流與非串流 Chat Completions
- 同模型多供應商路由、優先級、權重與故障切換
- 通道連續失敗自動冷卻
- API Key RPM/TPM 限流（正式環境使用 Redis）
- 呼叫前餘額預扣及完成後依實際 Token 結算
- 後端 31 模型能力目錄（28 Chat、3 Image）
- `/v1/images/generations` 圖片生成與按張計費
- 依實際 input/output tokens 扣款
- 收入、上游成本、延遲及錯誤日誌
- 與 NexToken 客戶網站同步 `/api/pricing`
- SQLite 本機資料庫與 Windows 一鍵啟停
- Alembic 資料庫 migration
- PostgreSQL 及 Redis 正式環境基礎

## 啟動方式

1. 雙擊 `Start-NexToken.bat`。
2. 目前這台電腦會直接使用已準備好的本機執行環境；搬到其他電腦時可改用 Docker Desktop。
3. 第一次啟動會自動建立 `.env`、管理員密碼與資料庫。
   本機執行環境預設保留 SQLite；Docker Compose 使用 PostgreSQL 及 Redis。
4. 切換正式容器環境前，將 `.env` 的 `NEXTOKEN_RUNTIME` 改為 `docker`，並先規劃既有 SQLite 資料搬遷。
4. 後台會自動開啟：`http://127.0.0.1:3100/admin`。

停止服務請雙擊 `Stop-NexToken.bat`。

## 第一次設定

1. 在「供應商」新增 OpenAI 相容通道，例如 `https://api.openai.com/v1`。
2. 儲存後按「測試」。
3. 在「模型價格」建立公開模型名稱、上游模型名稱、成本與售價。
4. 到客戶控制台註冊測試帳戶。
5. 在管理後台為測試帳戶增加餘額。
6. 客戶建立 API Key 後即可呼叫本機 `/v1/chat/completions`。

## 目前限制

- 第一版只支援 OpenAI 相容的上游通道。
- 31 個目錄模型只有在管理後台配置合法且可用的上游路由後，才會出現在 `/v1/models`。
- 付款 webhook、退款與公開部署尚未加入。
- SQLite 適合單機與封閉測試；正式多人營運應改用 PostgreSQL。
- `APP_SECRET` 變更後，既有供應商 API Key 將無法解密。

## 安全

- `.env` 和 `data/` 已排除於 Git。
- 不要把供應商 API Key 放進前端、公開 GitHub 或聊天訊息。
- 公開部署前必須限制 CORS、改用 PostgreSQL、加入 HTTPS、備份及速率限制。

## 資料庫 migration

啟動腳本會先執行 `python scripts/migrate.py`。既有第一版 SQLite 資料庫首次執行時會安全登記為初始版本，新資料庫則會由 Alembic 建立完整 schema。

手動檢查目前版本：

```powershell
.\.venv\Scripts\python.exe -m alembic current
```

建立新 migration：

```powershell
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "change description"
```
