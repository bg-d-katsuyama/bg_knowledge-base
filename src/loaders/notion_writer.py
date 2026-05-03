"""Notion への書き込みクライアント（スケルトン）.

実装方針:
- KnowledgeEntry → Notion ページのプロパティ変換
- レート制限対応（指数バックオフ、平均3req/秒）
- Rich Text の2,000文字制限への対応（超過時はBlockに分割）
- 詳細は `.claude/skills/notion_schema.md` を参照

実装は Phase 1 で追加する。
"""

from __future__ import annotations

# TODO(Phase 1): Notion 書き込みクライアントを実装
