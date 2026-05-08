"""score-positive メモ候補をバッチ取り込みするスクリプト.

`scripts/discover_memos.py` のヒューリスティックでスコアが付いたメモ候補を
すべて発見し、`ingest_notion_page` パイプラインで KB DB に取り込む。

既に取り込み済みのページは外部キー（SHA256）で重複検出され、UPSERT 動作で更新される。

実行方法:
    uv run python scripts/ingest_memo_candidates.py

推定コスト: $3〜8（106 件想定、Sonnet 4.x 単価）
推定所要時間: 30〜60 分（Notion API + Claude API のレイテンシ）
"""

from __future__ import annotations

import re
import sys
import time
from typing import Any, cast

from notion_client import Client as NotionClient

from src.common.config import settings
from src.common.logger import get_logger
from src.common.models import SourceType
from src.pipelines.notion_to_kb import ingest_notion_page

logger = get_logger(__name__)


KB_EXCLUDED_DB_IDS = {
    settings.notion_db_knowledge_entry,
    settings.notion_db_people,
    settings.notion_db_organization,
    settings.notion_db_project,
    settings.notion_db_tag,
}

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
]
DATE_PATTERN = re.compile(r"(20\d{2}[-/年]?\d{1,2}[-/月]?\d{1,2}日?)")


def _memo_score(title: str) -> int:
    """メモらしさのスコア（>0 で候補）を返す."""
    score = 0
    for kw in MEMO_KEYWORDS:
        if kw in title:
            score += 2
            break
    if DATE_PATTERN.search(title):
        score += 3
    return score


def _extract_title(obj: dict[str, Any]) -> str:
    for prop in (obj.get("properties") or {}).values():
        if prop.get("type") == "title":
            arr = prop.get("title") or []
            return "".join(t.get("plain_text", "") for t in arr)
    return ""


def discover_candidates() -> list[dict[str, Any]]:
    """ワークスペースを走査し、スコア > 0 のメモ候補を返す."""
    client = NotionClient(auth=settings.notion_api_token)
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "page_size": 100,
            "filter": {"value": "page", "property": "object"},
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
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
            if parent_id in KB_EXCLUDED_DB_IDS:
                continue
            title = _extract_title(obj)
            score = _memo_score(title)
            if score > 0:
                candidates.append(
                    {
                        "id": oid,
                        "title": title,
                        "score": score,
                        "last_edited_time": obj.get("last_edited_time", ""),
                    }
                )
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
    candidates.sort(
        key=lambda c: (-c["score"], c["last_edited_time"]),
        reverse=False,
    )
    return candidates


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("[1/3] メモ候補を発見中...", flush=True)
    candidates = discover_candidates()
    n = len(candidates)
    print(f"      → {n} 件のメモ候補を発見\n", flush=True)

    if not candidates:
        print("候補が見つかりませんでした。終了します。", flush=True)
        return 0

    print(f"[2/3] バッチ取り込み開始（{n} 件）", flush=True)
    success = 0
    skipped = 0
    failed = 0
    for i, c in enumerate(candidates, 1):
        title_snippet = (c["title"] or "(no title)")[:60]
        try:
            _, created = ingest_notion_page(c["id"], source_type=SourceType.MANUAL)
            action = "新規" if created else "更新"
            success += 1
            print(
                f"  [{i:3d}/{n}] OK   {action} | {title_snippet}",
                flush=True,
            )
        except RuntimeError as e:
            if "本文が空" in str(e):
                skipped += 1
                print(
                    f"  [{i:3d}/{n}] SKIP 空本文 | {title_snippet}",
                    flush=True,
                )
            else:
                failed += 1
                print(
                    f"  [{i:3d}/{n}] FAIL | {title_snippet} | {e}",
                    flush=True,
                )
        except Exception as e:
            failed += 1
            print(
                f"  [{i:3d}/{n}] FAIL | {title_snippet} | {type(e).__name__}: {e}",
                flush=True,
            )
        # Notion API レート制限への配慮（短いスリープ）
        time.sleep(0.3)

    print("\n[3/3] バッチ完了", flush=True)
    print(f"  success: {success}", flush=True)
    print(f"  skipped: {skipped} (本文が空)", flush=True)
    print(f"  failed:  {failed}", flush=True)
    print(f"  total:   {n}", flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
