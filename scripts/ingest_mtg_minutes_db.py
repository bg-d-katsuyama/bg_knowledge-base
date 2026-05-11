"""MTG Minutes DB から KB DB へのバッチ取り込みスクリプト.

久保田様より共有された MTG Minutes DB（id=62b461da16f94c5abe673f6127fdc856）
配下の全ページに対して、要約・エンティティ抽出・タグ生成・主述補完を実行し、
KB DB に UPSERT する。

実行方法:
    # 動作確認（先頭 3 件のみ）
    uv run python scripts/ingest_mtg_minutes_db.py --limit 3

    # 全件処理
    uv run python scripts/ingest_mtg_minutes_db.py

    # チェックポイント機能: 既に KB に外部キーが存在するページはスキップ
    uv run python scripts/ingest_mtg_minutes_db.py --skip-existing

    # 特定の page_id のみ処理（カンマ区切り）
    uv run python scripts/ingest_mtg_minutes_db.py --pages id1,id2,id3

オプション:
    --limit N            : 先頭 N 件のみ処理（デフォルト: 全件）
    --offset N           : 先頭 N 件をスキップ（デフォルト: 0）
    --skip-existing      : 既に KB に存在するページはスキップ
    --no-entity          : エンティティ抽出を無効化
    --no-tag             : タグ生成を無効化
    --no-revise          : 主述補完を無効化
    --pages id1,id2,...  : 特定ページのみ処理（カンマ区切り）

備考:
    - 推定コスト: 868 件で $30〜80（フル機能）
    - 推定所要時間: 868 件で 90〜180 分
    - Notion API レート制限への配慮で 0.3 秒スリープを挟む
    - 失敗・スキップは続行する（途中で止めない）
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import traceback
from typing import Any, cast
from urllib.parse import urlparse

from notion_client import Client as NotionClient

from src.common.config import settings
from src.common.logger import get_logger
from src.common.models import SourceType
from src.pipelines.notion_to_kb import KnowledgeIngestionPipeline

logger = get_logger(__name__)

INDEX_DB_ID = "62b461da16f94c5abe673f6127fdc856"


def _normalize_id(raw: str) -> str:
    return raw.replace("-", "").lower()


def _page_id_from_url(url: str) -> str | None:
    if not url:
        return None
    try:
        path = urlparse(url).path
    except Exception:
        return None
    seg = path.rstrip("/").split("/")[-1]
    m = re.search(r"([0-9a-fA-F]{32})", seg)
    if m:
        return m.group(1).lower()
    return None


def _extract_title(obj: dict[str, Any]) -> str:
    for prop in (obj.get("properties") or {}).values():
        if prop.get("type") == "title":
            arr = prop.get("title") or []
            return "".join(t.get("plain_text", "") for t in arr)
    return ""


def list_mtg_minutes_pages(client: NotionClient) -> list[dict[str, Any]]:
    db = cast(dict[str, Any], client.databases.retrieve(database_id=INDEX_DB_ID))
    sources = db.get("data_sources") or []
    if not sources:
        raise RuntimeError("MTG Minutes DB has no data_sources")
    ds_id = cast(str, sources[0]["id"])
    pages: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {"data_source_id": ds_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        res = cast(dict[str, Any], client.data_sources.query(**kwargs))
        for row in res.get("results", []):
            pages.append(row)
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return pages


def list_existing_kb_source_ids(client: NotionClient) -> set[str]:
    """KB DB の現存エントリの source_page_id（ハイフン無し小文字）集合を返す."""
    db_id = settings.notion_db_knowledge_entry
    db = cast(dict[str, Any], client.databases.retrieve(database_id=db_id))
    ds_id = cast(str, db["data_sources"][0]["id"])
    ids: set[str] = set()
    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {"data_source_id": ds_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        res = cast(dict[str, Any], client.data_sources.query(**kwargs))
        for row in res.get("results", []):
            props = row.get("properties", {}) or {}
            url = (props.get("ソースURL") or {}).get("url") or ""
            spid = _page_id_from_url(url)
            if spid:
                ids.add(spid)
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return ids


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--no-entity", action="store_true")
    parser.add_argument("--no-tag", action="store_true")
    parser.add_argument("--no-revise", action="store_true")
    parser.add_argument("--pages", type=str, default=None, help="カンマ区切りの page_id")
    parser.add_argument("--sleep", type=float, default=0.3)
    args = parser.parse_args()

    pipeline = KnowledgeIngestionPipeline(
        enable_entity_extraction=not args.no_entity,
        enable_tagging=not args.no_tag,
        enable_body_revision=not args.no_revise,
    )
    client = pipeline.notion_client

    print("[1/3] MTG Minutes DB の全ページを列挙中...", flush=True)
    pages: list[dict[str, Any]]
    if args.pages:
        target_ids = {_normalize_id(p.strip()) for p in args.pages.split(",") if p.strip()}
        all_pages = list_mtg_minutes_pages(client)
        pages = [p for p in all_pages if _normalize_id(p["id"]) in target_ids]
    else:
        pages = list_mtg_minutes_pages(client)
    print(f"      → DB 内ページ数: {len(pages)}", flush=True)

    existing_ids: set[str] = set()
    if args.skip_existing:
        print("[1.5/3] 既存 KB エントリの source_page_id を取得中...", flush=True)
        existing_ids = list_existing_kb_source_ids(client)
        print(f"      → KB 既存件数: {len(existing_ids)}", flush=True)

    if args.offset:
        pages = pages[args.offset :]
    if args.limit is not None:
        pages = pages[: args.limit]

    n = len(pages)
    print(f"[2/3] バッチ取り込み開始: {n} 件", flush=True)
    print(
        f"      モード: entity={not args.no_entity} tag={not args.no_tag} "
        f"revise={not args.no_revise} skip_existing={args.skip_existing}",
        flush=True,
    )

    success_new = 0
    success_upd = 0
    skipped = 0
    failed = 0
    for i, p in enumerate(pages, 1):
        pid_raw = p["id"]
        pid_norm = _normalize_id(pid_raw)
        title = _extract_title(p)
        title_snip = (title or "(no title)")[:60]

        if args.skip_existing and pid_norm in existing_ids:
            skipped += 1
            print(f"  [{i:4d}/{n}] SKIP (existing) | {title_snip}", flush=True)
            continue

        try:
            result = pipeline.ingest(page_id=pid_raw, source_type=SourceType.MANUAL)
            if result.created:
                success_new += 1
                action = "新規"
            else:
                success_upd += 1
                action = "更新"
            print(
                f"  [{i:4d}/{n}] OK {action} | "
                f"P{result.n_people} O{result.n_organizations} "
                f"Pj{result.n_projects} T{result.n_tags} "
                f"body {result.body_chars_original}->{result.body_chars_revised} | "
                f"{title_snip}",
                flush=True,
            )
        except RuntimeError as e:
            if "本文が空" in str(e):
                skipped += 1
                print(f"  [{i:4d}/{n}] SKIP (empty body) | {title_snip}", flush=True)
            else:
                failed += 1
                print(f"  [{i:4d}/{n}] FAIL | {title_snip} | {e}", flush=True)
        except Exception as e:
            failed += 1
            print(
                f"  [{i:4d}/{n}] FAIL | {title_snip} | {type(e).__name__}: {e}",
                flush=True,
            )
            traceback.print_exc()
        time.sleep(args.sleep)

    print("\n[3/3] バッチ完了", flush=True)
    print(f"  success_new: {success_new}", flush=True)
    print(f"  success_upd: {success_upd}", flush=True)
    print(f"  skipped:     {skipped}", flush=True)
    print(f"  failed:      {failed}", flush=True)
    print(f"  total:       {n}", flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
