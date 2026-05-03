"""認証ヘルパー（スケルトン）.

Google API・Notion・Slack・Anthropic それぞれのクライアント生成と認証を集約する。

実装方針:
- 本番では Workload Identity Federation を優先（鍵ファイル不使用）
- ローカルでは `.env` の認証情報を使用
- 全クライアントは `lru_cache` でシングルトン化

実装は Phase 1 着手時に追加する。
"""

from __future__ import annotations

# TODO(Phase 1): Notion / Anthropic / GCP / Slack 各クライアントのファクトリを実装する
# - get_notion_client() -> notion_client.Client
# - get_anthropic_client() -> anthropic.Anthropic
# - get_gdrive_client() -> googleapiclient.discovery.Resource
# - get_slack_client() -> slack_sdk.WebClient
