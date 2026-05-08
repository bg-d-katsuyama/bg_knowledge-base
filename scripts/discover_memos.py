"""Notion ワークスペースから取り込み試験用のメモ候補を発見するスクリプト.

接続済みの全ページを走査し、メモらしき候補（タイトル・更新日時・親タイプを基に
ヒューリスティックで判定）を抽出する。本日の Phase 1 試験取り込みで使う 1 件を
選定するために使用。

実行方法:
    uv run python scripts/discover_memos.py
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from typing import Any, cast

from notion_client import Client as NotionClient

from src.common.config import settings

# 取り込み対象から除外する KB 内部のページ・データソース ID（重複混入防止）
KB_EXCLUDED_DB_IDS = {
    settings.notion_db_knowledge_entry,
    settings.notion_db_people,
    settings.notion_db_organization,
    settings.notion_db_project,
    settings.notion_db_tag,
}


# メモらしさを判定するキーワード（タイトルに含まれる場合スコア加算）
MEMO_KEYWORDS = [
    "ミーティング",
    "MTG",
    "mtg",
    "meeting",
    "Meeting",
    "議事",
    "打ち合わせ",
    "打合せ",
    "打ち合せ",
    "メモ",
    "memo",
    "Memo",
    "週次",
    "月次",
    "定例",
    "アジェンダ",
    "Agenda",
    "1on1",
    "1on1",
]

# 日付らしいパターン（YYYY-MM-DD, YYYY/MM/DD, YYYYMMDD, YYYY年MM月DD日）
DATE_PATTERN = re.compile(r"(20\d{2}[-/年]?\d{1,2}[-/月]?\d{1,2}日?)")


def extract_title(obj: dict[str, Any]) -> str:
    """ページレスポンスからタイトル文字列を抽出する."""
    for prop in (obj.get("properties") or {}).values():
        if prop.get("type") == "title":
            arr = prop.get("title") or []
            return "".join(t.get("plain_text", "") for t in arr)
    return ""


def memo_score(title: str) -> int:
    """タイトルからメモらしさのスコアを算出する."""
    score = 0
    for kw in MEMO_KEYWORDS:
        if kw in title:
            score += 2
            break
    if DATE_PATTERN.search(title):
        score += 3
    return score


def main() -> int:
    # Windows コンソール対策: stdout を UTF-8 に
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not settings.notion_api_token:
        print("ERROR: NOTION_API_TOKEN is not set", file=sys.stderr)
        return 1

    client = NotionClient(auth=settings.notion_api_token)
    seen: set[str] = set()
    pages: list[dict[str, Any]] = []

    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "page_size": 100,
            "filter": {"value": "page", "property": "object"},
            "sort": {
                "direction": "descending",
                "timestamp": "last_edited_time",
            },
        }
        if cursor:
            kwargs["start_cursor"] = cursor
        result = cast(dict[str, Any], client.search(**kwargs))
        for obj in result.get("results", []):
            oid = obj["id"]
            if oid in seen:
                continue
            seen.add(oid)
            parent = obj.get("parent", {}) or {}
            parent_id = (
                parent.get("database_id")
                or parent.get("page_id")
                or parent.get("data_source_id")
                or ""
            )
            # KB 内部のページは除外
            if parent_id in KB_EXCLUDED_DB_IDS:
                continue
            title = extract_title(obj)
            pages.append(
                {
                    "id": oid,
                    "title": title,
                    "last_edited_time": obj.get("last_edited_time", ""),
                    "parent_type": parent.get("type", "?"),
                    "parent_id": parent_id,
                    "url": obj.get("url", ""),
                    "score": memo_score(title),
                }
            )
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")

    print(f"== 接続済みアクセス可能ページ: {len(pages)} 件 ==\n")

    parent_dist = Counter(p["parent_type"] for p in pages)
    print("親タイプの分布:")
    for k, v in parent_dist.most_common():
        print(f"  {k}: {v}")
    print()

    # ヒューリスティックスコアの高い候補
    scored = [p for p in pages if p["score"] > 0]
    scored.sort(key=lambda p: (-p["score"], p["last_edited_time"]), reverse=False)
    scored.sort(key=lambda p: (-p["score"], p["last_edited_time"][::-1]))

    print(f"== メモらしい候補（スコア > 0）: {len(scored)} 件 ==")
    for i, p in enumerate(scored[:20], 1):
        title_disp = p["title"][:60] or "(no title)"
        print(
            f"  [{i:2d}] score={p['score']} "
            f"{p['last_edited_time'][:10]} | "
            f"parent={p['parent_type']:13s} | "
            f"{title_disp}"
        )
        print(f"       URL: {p['url']}")
    print()

    print("== 直近更新の上位 20 件（参考、全体）==")
    for i, p in enumerate(pages[:20], 1):
        title_disp = p["title"][:60] or "(no title)"
        print(
            f"  [{i:2d}] {p['last_edited_time'][:10]} | "
            f"parent={p['parent_type']:13s} | {title_disp}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
