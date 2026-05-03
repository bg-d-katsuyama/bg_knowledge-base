# infra/ — インフラ定義

GCPリソースの宣言的定義を配置するディレクトリ。

## 配置予定

| ファイル | 内容 | フェーズ |
|---|---|---|
| `cloud_run.yaml` | Cloud Run Jobs / Service の定義 | Phase 1〜3 |
| `scheduler.yaml` | Cloud Scheduler ジョブ定義 | Phase 1 |
| `iam.yaml` | サービスアカウントとIAMバインディング | Phase 0 |

## 方針

- 初期は `gcloud` コマンドベースで構築し、`docs/runbook.md` に手順を記録
- 規模が大きくなったら Terraform 化を検討
- 本番リソースの破壊的変更は必ず人間の承認を経ること（CLAUDE.md セクション7参照）
