# 運用手順書（Runbook）

本ドキュメントは BG Knowledge Base の運用手順をまとめたものです。

---

## 1. 定期作業

### 日次
- Cloud Schedulerによる自動同期（02:00 JST）
- エラーログの確認（Cloud Loggingで `severity>=ERROR` を確認）

### 週次
- Claude API の使用量・コストを `docs/api_cost_tracking.md` に記録
- 処理ステータス「未処理」「AI加工済」のエントリ件数を確認

### 月次
- 全DB の Relation 整合性チェック（孤立ノードの検出）
- 同名別人エントリの分離作業

### 四半期
- 権限棚卸し（Notion / GitHub / GCP / Slack）
- サービスアカウント鍵のローテーション
- コスト見直しとモデル使い分けの最適化

---

## 2. 同期の手動実行

責任者は Slack で以下のコマンドを実行できます。

| コマンド | 動作 |
|---|---|
| `/kb-sync notion` | Notion既存メモの同期を即時実行 |
| `/kb-sync drive` | Google Drive同期を即時実行 |
| `/kb-sync all` | 全ソースの同期を実行 |
| `/kb-status` | 最終同期日時・処理件数を返す |
| `/kb-rebuild <entry_id>` | 特定エントリの再処理 |
| `/kb-search <query>` | 簡易検索（Phase 4） |

**実行権限**: Slackユーザーグループ `@kb-admins` のメンバーのみ。

---

## 3. インシデント対応

### 同期が失敗した場合

1. Cloud Logging でエラー内容を確認
2. 原因の切り分け
   - 認証エラー → Secret Manager の値を確認
   - レート制限 → リトライ間隔を確認、必要なら手動再実行
   - スキーマ不整合 → Notion DB の構成を確認
3. 必要なら `/kb-rebuild` で個別エントリを再処理
4. インシデント内容を `docs/decision_log.md` に記録

### Claude API が異常に高額になった場合

1. Cloud Logging でリクエスト数を確認
2. 無限ループや重複処理がないかチェック
3. 必要なら Cloud Run Jobs を一時停止
4. プロンプトキャッシング・Batch APIの設定を確認

### 退職・異動時の対応フロー

1. 対象者のNotion権限を削除
2. 対象者がSlackコマンド権限保有者の場合、`@kb-admins` から除外
3. GitHubアクセスを剥奪
4. Secret Managerは影響なし（サービスアカウント運用のため）

---

## 4. デプロイ手順

### 本番デプロイ

```bash
# main ブランチへのマージで GitHub Actions 経由で自動デプロイ
# 手動デプロイが必要な場合のみ以下:

gcloud auth login
gcloud config set project ${GCP_PROJECT_ID}

# Cloud Run Jobs（バッチ）
gcloud run jobs deploy kb-sync \
  --source . \
  --region asia-northeast1 \
  --service-account kb-runner@${GCP_PROJECT_ID}.iam.gserviceaccount.com

# Cloud Run（Slack Bot 常駐）
gcloud run deploy kb-bot \
  --source . \
  --region asia-northeast1 \
  --service-account kb-runner@${GCP_PROJECT_ID}.iam.gserviceaccount.com
```

**注意**: 本番デプロイ前は必ず以下を確認
- [ ] テストが全て通っている（CI緑）
- [ ] decision_log.md に変更内容を記録
- [ ] Notion本番DBへの破壊的変更がない

---

## 5. Secret Manager の管理

### シークレットの追加

```bash
echo -n "the-secret-value" | gcloud secrets create <secret-name> \
  --data-file=- \
  --replication-policy=automatic
```

### シークレットの更新

```bash
echo -n "the-new-value" | gcloud secrets versions add <secret-name> \
  --data-file=-
```

### サービスアカウントへのアクセス権付与

```bash
gcloud secrets add-iam-policy-binding <secret-name> \
  --member="serviceAccount:kb-runner@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### 管理対象シークレット一覧

| Secret 名 | 用途 |
|---|---|
| `anthropic-api-key` | Claude API |
| `notion-api-token` | Notion API |
| `slack-bot-token` | Slack Bot |
| `slack-signing-secret` | Slack 署名検証 |
| `slack-app-token` | Slack Socket Mode（必要に応じて） |

---

## 6. ログとモニタリング

- **Cloud Logging**: 全実行ログが自動集約
- **重要なフィルタ**:
  - `resource.type="cloud_run_job" AND severity>=ERROR`
  - `jsonPayload.event="claude_api_call"`（コスト追跡用）
  - `jsonPayload.event="notion_write"`（書き込み追跡用）

---

## 7. ローカル開発の安全確認

ローカルから本番Notionを誤って書き換えないため、以下を徹底：

- 開発環境専用のNotion DBを別途用意（推奨）
- `.env` の `APP_ENV=local` を確認
- 本番DBへの書き込みコードには `if settings.app_env == "prod"` ガードを追加
