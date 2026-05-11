"""MTG Minutes DB と KB DB の差分調査スクリプト.

久保田様より共有された MTG Minutes DB（id=62b461da16f94c5abe673f6127fdc856）の
配下ページを列挙し、KB DB に登録済みエントリとの差分を出す。

実行方法:
    uv run python scripts/diff_mtg_minutes_db.py

備考:
    本スクリプトは読み取りのみ。書き込みは一切行わない。
"""

from __future__ import annotations

import re
import sys
from typing import Any, cast
from urllib.parse import urlparse

from notion_client import Client as NotionClient

from src.common.config import settings

INDEX_DB_ID = "62b461da16f94c5abe673f6127fdc856"


def _normalize_id(raw: str) -> str:
    return raw.replace("-", "").lower()


def _page_id_from_url(url: str) -> str | None:
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
    """MTG Minutes DB 配下の全ページを返す."""
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


def list_kb_entries(client: NotionClient) -> list[dict[str, Any]]:
    db_id = settings.notion_db_knowledge_entry
    db = cast(dict[str, Any], client.databases.retrieve(database_id=db_id))
    ds_id = cast(str, db["data_sources"][0]["id"])

    entries: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {"data_source_id": ds_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        res = cast(dict[str, Any], client.data_sources.query(**kwargs))
        for row in res.get("results", []):
            props = row.get("properties", {}) or {}
            title_arr = (props.get("タイトル") or {}).get("title") or []
            title = "".join(t.get("plain_text", "") for t in title_arr)
            source_url = (props.get("ソースURL") or {}).get("url") or ""
            entries.append(
                {
                    "kb_page_id": row["id"],
                    "title": title,
                    "source_url": source_url,
                    "source_page_id": _page_id_from_url(source_url),
                }
            )
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return entries


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    client = NotionClient(auth=settings.notion_api_token)

    print("=" * 70, flush=True)
    print("[A] MTG Minutes DB 配下のページ列挙", flush=True)
    print("=" * 70, flush=True)
    mtg_pages = list_mtg_minutes_pages(client)
    print(f"  MTG Minutes DB 配下のページ数: {len(mtg_pages)}", flush=True)

    print("\n" + "=" * 70, flush=True)
    print("[B] KB DB に登録済みのエントリ", flush=True)
    print("=" * 70, flush=True)
    kb_entries = list_kb_entries(client)
    kb_source_ids = {
        e["source_page_id"] for e in kb_entries if e.get("source_page_id")
    }
    print(f"  KB DB エントリ数: {len(kb_entries)}", flush=True)

    print("\n" + "=" * 70, flush=True)
    print("[C] MTG Minutes DB のうち KB に未登録", flush=True)
    print("=" * 70, flush=True)
    unregistered: list[dict[str, Any]] = []
    for p in mtg_pages:
        pid = _normalize_id(p["id"])
        if pid not in kb_source_ids:
            title = _extract_title(p)
            unregistered.append(
                {
                    "id": pid,
                    "title": title,
                    "url": p.get("url", ""),
                    "last_edited_time": p.get("last_edited_time", ""),
                }
            )
    unregistered.sort(key=lambda c: c["title"])
    for c in unregistered:
        print(f"  - {c['title']!r}", flush=True)
        print(f"      id={c['id']}  url={c['url']}", flush=True)
    print(f"  合計: {len(unregistered)} 件", flush=True)

    print("\n" + "=" * 70, flush=True)
    print("[D] KB に登録済みだが MTG Minutes DB には存在しないエントリ", flush=True)
    print("=" * 70, flush=True)
    mtg_ids = {_normalize_id(p["id"]) for p in mtg_pages}
    kb_only: list[dict[str, Any]] = []
    for e in kb_entries:
        spid = e.get("source_page_id")
        if spid and spid not in mtg_ids:
            kb_only.append(e)
    for e in kb_only:
        print(f"  - {e['title']!r}", flush=True)
        print(f"      url={e['source_url']}  source_page_id={e['source_page_id']}", flush=True)
    print(f"  合計: {len(kb_only)} 件", flush=True)

    print("\n" + "=" * 70, flush=True)
    print("[F] サマリー", flush=True)
    print("=" * 70, flush=True)
    print(f"  MTG Minutes DB 配下     : {len(mtg_pages)}", flush=True)
    print(f"  KB 登録済み              : {len(kb_entries)}", flush=True)
    print(f"  未登録（取り込むべき）   : {len(unregistered)}", flush=True)
    print(f"  KB のみ（DB外）          : {len(kb_only)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
