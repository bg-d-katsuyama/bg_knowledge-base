"""作成済み Notion DB のプロパティ一覧を確認するスクリプト.

API レベルで各DBのプロパティが期待通り作成されているかを検証する。
Notion UI 上でプロパティが見えない場合に、それが「未作成」なのか
「ビューで非表示」なのかを切り分けるために使用する。

実行方法:
    uv run python scripts/inspect_schema.py
"""

from __future__ import annotations

import sys
from typing import Any, cast

from notion_client import Client as NotionClient
from notion_client.errors import APIResponseError

from src.common.config import settings


def inspect(client: NotionClient, label: str, db_id: str) -> None:
    """指定 DB のプロパティ名と型を一覧表示する."""
    print(f"\n=== {label} ===")
    print(f"  ID: {db_id}")
    if not db_id:
        print("  [SKIP] DB ID が未設定です")
        return
    try:
        db = cast(dict[str, Any], client.databases.retrieve(database_id=db_id))
    except APIResponseError as e:
        print(f"  [ERROR] {e}")
        return

    props = db.get("properties", {})
    print(f"  プロパティ数: {len(props)}")
    print(f"  [DEBUG] response keys: {list(db.keys())}")
    print(f"  [DEBUG] object type:    {db.get('object')}")
    if not props:
        # 上位5キーを生のまま見る
        import json as _json

        snippet = {k: db[k] for k in list(db.keys())[:8] if k in db}
        print("  [DEBUG] raw snippet:")
        print(_json.dumps(snippet, ensure_ascii=False, indent=2, default=str))
    for name, schema in props.items():
        ptype = schema.get("type", "?")
        extra = ""
        if ptype == "relation":
            target = schema.get("relation", {}).get("database_id", "?")
            extra = f" -> {target}"
        elif ptype == "select":
            opts = [o.get("name") for o in schema.get("select", {}).get("options", [])]
            extra = f" options={opts}"
        elif ptype == "multi_select":
            opts = [o.get("name") for o in schema.get("multi_select", {}).get("options", [])]
            extra = f" options={opts}"
        print(f"    - {name}: {ptype}{extra}")


def main() -> int:
    if not settings.notion_api_token:
        print("ERROR: NOTION_API_TOKEN is not set", file=sys.stderr)
        return 1

    client = NotionClient(auth=settings.notion_api_token)
    inspect(client, "企業・団体DB", settings.notion_db_organization)
    inspect(client, "人DB", settings.notion_db_people)
    inspect(client, "プロジェクトDB", settings.notion_db_project)
    inspect(client, "タグDB", settings.notion_db_tag)
    inspect(client, "ナレッジエントリDB", settings.notion_db_knowledge_entry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
