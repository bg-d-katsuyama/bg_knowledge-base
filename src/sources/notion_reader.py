"""Notion 既存メモのリーダー（スケルトン）.

実装方針:
- 既存の Meeting メモ DB を `notion_client.databases.query` で読み取る
- ページネーション処理（100件単位）
- 最終更新日時で差分検出
- ページ本文（Block）を再帰取得

実装は Phase 1 で追加する。
"""

from __future__ import annotations

# TODO(Phase 1): Notion 既存メモ DB の読み取り実装
