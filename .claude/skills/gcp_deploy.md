# スキル: GCPデプロイ

GCPリソースの設計・デプロイに関する指針。

## リソース構成

| リソース | 用途 |
|---|---|
| Cloud Run Jobs | バッチ同期処理（`kb-sync`） |
| Cloud Run Service | Slack Bot常駐（`kb-bot`） |
| Cloud Scheduler | 日次・時間ごとのジョブ起動 |
| Secret Manager | 全シークレット管理 |
| Cloud Storage | 生データバックアップ・処理ログ |
| Cloud Logging | 全実行ログ集約 |

## サービスアカウント

`kb-runner@${GCP_PROJECT_ID}.iam.gserviceaccount.com` を作成し、以下のロールを最小権限で付与：

- `roles/secretmanager.secretAccessor`（特定シークレットのみ）
- `roles/storage.objectAdmin`（特定バケットのみ）
- `roles/logging.logWriter`
- `roles/run.invoker`（Schedulerが Cloud Run Jobs を起動するため）

## デプロイは GitHub Actions 経由が原則

`.github/workflows/deploy.yml` で main ブランチへのマージ時に自動デプロイ。手動デプロイは緊急時のみ。

## Workload Identity Federation

ローカル開発以外ではサービスアカウント鍵ファイルを使わず、Workload Identity Federation を使用：

- GitHub Actions → GCP は OIDC 経由で認証
- Cloud Run → 他GCPサービスはサービスアカウント直接付与

## 初期セットアップ手順（Phase 0）

```bash
# 1. プロジェクト作成
gcloud projects create bg-knowledge-base-prod --name="BG Knowledge Base"

# 2. 必要なAPIを有効化
gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  logging.googleapis.com \
  iam.googleapis.com

# 3. サービスアカウント作成
gcloud iam service-accounts create kb-runner \
  --display-name="BG KB Runner"

# 4. シークレット用バケット作成
gcloud storage buckets create gs://bg-kb-rawdata-prod \
  --location=asia-northeast1

# 5. シークレット登録（runbook.md を参照）
```

## コスト目安（GCP分）

- 小規模利用想定で月額 $5〜$20
- Cloud Run の最小インスタンス数は0、ピーク時のみスケールアップ
- Cloud Logging は標準で30日保持。長期保管が必要なら Cloud Storage にエクスポート

## 環境分離

- `bg-knowledge-base-dev`: 開発・検証用
- `bg-knowledge-base-prod`: 本番

`.env` の `APP_ENV` で切り替え。`prod` の場合のみ本番リソースに接続するガードを各処理に設ける。
