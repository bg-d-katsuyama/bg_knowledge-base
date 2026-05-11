"""アクセス可能ページと KB DB 登録状況の差分調査スクリプト.

目的:
    1. 現在 Integration からアクセス可能な全ページを取得（search API）
    2. KB DB に登録済みの全エントリ（タイトル + ソース URL + 外部キー）を取得
    3. 以下を出力:
        - KB に登録されているが現在アクセスできない（接続解除候補）
        - 現在アクセス可能な「メモ候補」のうち KB に未登録
        - メモ index ページ（INDEX_PAGE_ID）の取得可否

実行方法:
    uv run python scripts/diff_accessibility.py

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

# 久保田様より共有されたメモ index ページ
INDEX_PAGE_ID = "62b461da16f94c5abe673f6127fdc856"


KB_DB_IDS_TO_EXCLUDE = {
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


def _normalize_id(raw: str) -> str:
    """ハイフン有無に関わらず 32 桁小文字 hex に正規化."""
    return raw.replace("-", "").lower()


def _page_id_from_url(url: str) -> str | None:
    """Notion URL の末尾セグメントから 32 桁 hex を抽出."""
    try:
        path = urlparse(url).path
    except Exception:
        return None
    seg = path.rstrip("/").split("/")[-1]
    m = re.search(r"([0-9a-fA-F]{32})", seg)
    if m:
        return m.group(1).lower()
    return None


def list_all_accessible_pages(client: NotionClient) -> list[dict[str, Any]]:
    """search API で取得できる全ページ（database 配下/単独問わず）を返す."""
    seen: set[str] = set()
    pages: list[dict[str, Any]] = []
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
            pid = obj["id"]
            if pid in seen:
                continue
            seen.add(pid)
            pages.append(obj)
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
    return pages


def list_kb_entries(client: NotionClient) -> list[dict[str, Any]]:
    """KB DB 内の全エントリを取得し、タイトル/ソースURL/外部キー/source_page_id を返す."""
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
            ext_arr = (props.get("外部キー") or {}).get("rich_text") or []
            external_key = "".join(t.get("plain_text", "") for t in ext_arr)
            entries.append(
                {
                    "kb_page_id": row["id"],
                    "title": title,
                    "source_url": source_url,
                    "source_page_id": _page_id_from_url(source_url),
                    "external_key": external_key,
                }
            )
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return entries


def try_retrieve_index(client: NotionClient) -> dict[str, Any]:
    """メモ index ページ自体を、page / database / data_source の各 API で試す."""
    result: dict[str, Any] = {"id": INDEX_PAGE_ID}
    try:
        client.pages.retrieve(page_id=INDEX_PAGE_ID)
        result["as_page"] = "OK"
    except Exception as e:  # noqa: BLE001
        result["as_page"] = f"NG: {type(e).__name__}: {str(e)[:120]}"
    try:
        client.databases.retrieve(database_id=INDEX_PAGE_ID)
        result["as_database"] = "OK"
    except Exception as e:  # noqa: BLE001
        result["as_database"] = f"NG: {type(e).__name__}: {str(e)[:120]}"
    try:
        client.blocks.children.list(block_id=INDEX_PAGE_ID, page_size=1)
        result["children_listable"] = "OK"
    except Exception as e:  # noqa: BLE001
        result["children_listable"] = f"NG: {type(e).__name__}: {str(e)[:120]}"
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    client = NotionClient(auth=settings.notion_api_token)

    print("=" * 70, flush=True)
    print("[A] メモ index ページ（共有されたページ）の取得可否", flush=True)
    print("=" * 70, flush=True)
    idx = try_retrieve_index(client)
    for k, v in idx.items():
        print(f"  {k:20s}: {v}", flush=True)

    print("\n" + "=" * 70, flush=True)
    print("[B] 現在 Integration からアクセス可能なページ（search API）", flush=True)
    print("=" * 70, flush=True)
    accessible_pages = list_all_accessible_pages(client)
    accessible_ids: set[str] = {_normalize_id(p["id"]) for p in accessible_pages}
    print(f"  全アクセス可能ページ数: {len(accessible_pages)}", flush=True)

    # KB DB 配下のページは除外してメモ候補をスコア
    candidates: list[dict[str, Any]] = []
    for p in accessible_pages:
        parent = p.get("parent", {}) or {}
        parent_id = (
            parent.get("database_id")
            or parent.get("page_id")
            or parent.get("data_source_id")
            or ""
        )
        if parent_id in KB_DB_IDS_TO_EXCLUDE:
            continue
        title = _extract_title(p)
        score = _memo_score(title)
        if score > 0:
            candidates.append(
                {
                    "id": _normalize_id(p["id"]),
                    "title": title,
                    "score": score,
                    "last_edited_time": p.get("last_edited_time", ""),
                    "url": p.get("url", ""),
                    "parent": parent,
                }
            )
    print(f"  メモ候補（score > 0、KB DB 配下を除く）: {len(candidates)}", flush=True)

    print("\n" + "=" * 70, flush=True)
    print("[C] KB DB に登録済みの全エントリ", flush=True)
    print("=" * 70, flush=True)
    kb_entries = list_kb_entries(client)
    print(f"  KB DB エントリ数: {len(kb_entries)}", flush=True)

    print("\n" + "=" * 70, flush=True)
    print("[D] 接続解除候補（KB に登録済みだが現在アクセス不可）", flush=True)
    print("=" * 70, flush=True)
    disconnected: list[dict[str, Any]] = []
    for e in kb_entries:
        spid = e.get("source_page_id")
        if not spid:
            continue
        if spid not in accessible_ids:
            disconnected.append(e)
    if disconnected:
        for e in disconnected:
            print(f"  - {e['title']!r}", flush=True)
            print(f"      url={e['source_url']}", flush=True)
            print(f"      source_page_id={e['source_page_id']}", flush=True)
    else:
        print("  （該当なし）", flush=True)
    print(f"  合計: {len(disconnected)} 件", flush=True)

    print("\n" + "=" * 70, flush=True)
    print("[E] 未登録メモ候補（アクセス可能だが KB に未登録）", flush=True)
    print("=" * 70, flush=True)
    kb_source_ids: set[str] = {
        e["source_page_id"] for e in kb_entries if e.get("source_page_id")
    }
    unregistered: list[dict[str, Any]] = []
    for c in candidates:
        if c["id"] not in kb_source_ids:
            unregistered.append(c)
    unregistered.sort(key=lambda c: (-c["score"], c["last_edited_time"]))
    if unregistered:
        for c in unregistered[:200]:
            print(
                f"  [score={c['score']}] {c['title']!r}",
                flush=True,
            )
            print(f"      id={c['id']}  url={c['url']}", flush=True)
        if len(unregistered) > 200:
            print(f"  ... 他 {len(unregistered) - 200} 件省略", flush=True)
    else:
        print("  （該当なし）", flush=True)
    print(f"  合計: {len(unregistered)} 件", flush=True)

    print("\n" + "=" * 70, flush=True)
    print("[F] サマリー", flush=True)
    print("=" * 70, flush=True)
    print(f"  アクセス可能ページ        : {len(accessible_pages)}", flush=True)
    print(f"  メモ候補（score > 0）      : {len(candidates)}", flush=True)
    print(f"  KB 登録済みエントリ        : {len(kb_entries)}", flush=True)
    print(f"  接続解除候補               : {len(disconnected)}", flush=True)
    print(f"  未登録メモ候補             : {len(unregistered)}", flush=True)
    print(f"  メモ index ページ取得      : page={idx['as_page']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
