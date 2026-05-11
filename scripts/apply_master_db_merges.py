"""discover_master_db_merges.py が出力した CSV を読み、実マージを適用するスクリプト.

各マージグループに対して:
1. 該当する Relation プロパティで「merge」側を参照している KB エントリを検索
2. その Relation を canonical 側に付け替え（重複は除去）
3. merge エントリを archive

実行方法:
    # 適用（実書き込み）
    uv run python scripts/apply_master_db_merges.py path/to/proposals.csv

    # ドライラン（書き込みなし、影響範囲だけ報告）
    uv run python scripts/apply_master_db_merges.py path/to/proposals.csv --dry-run

オプション:
    --dry-run        : 実書き込みせず、影響件数だけ表示
    --kind {人,...}  : 特定の kind のみ適用
    --sleep SEC      : Notion API 呼び出し間スリープ（既定 0.3）

CSV フォーマット（discover が出力するもの）:
    kind, cluster_id, role(canonical|merge), name, page_id, reason, approve(Y/N)
    `approve='N'` のクラスタは丸ごとスキップ。
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

from notion_client import Client as NotionClient

from src.common.config import settings
from src.common.logger import get_logger

logger = get_logger(__name__)


# kind → KB DB の Relation プロパティ名（複数指す可能性あり）
_KB_RELATION_PROPS: dict[str, list[str]] = {
    "人": ["関係者（人）", "作成者"],
    "企業・団体": ["関係先（組織）"],
    "プロジェクト": ["関連プロジェクト"],
    "タグ": ["内容タグ"],
}


def _normalize_id(s: str) -> str:
    return s.replace("-", "").lower()


def _read_csv(path: Path) -> dict[str, dict[str, Any]]:
    """CSV を cluster_id ごとにまとめる.

    Returns:
        ``{cluster_id: {"kind": ..., "approve": "Y"/"N", "canonical": (name, id),
                        "merges": [(name, id), ...]}}``
    """
    clusters: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = row["cluster_id"]
            kind = row["kind"]
            role = row["role"]
            name = row["name"]
            pid = row["page_id"]
            approve = (row.get("approve") or "Y").strip().upper()
            entry = clusters.setdefault(
                cid,
                {
                    "kind": kind,
                    "approve": approve,
                    "canonical": None,
                    "merges": [],
                },
            )
            # クラスタ内で approve は最初の行を採用
            if role == "canonical":
                entry["canonical"] = (name, pid)
            elif role == "merge":
                entry["merges"].append((name, pid))
    return clusters


def _find_kb_referencing(
    notion_client: NotionClient,
    kb_ds_id: str,
    relation_prop: str,
    target_id: str,
) -> list[dict[str, Any]]:
    """指定 Relation プロパティが ``target_id`` を含む KB エントリを返す."""
    results: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        kw: dict[str, Any] = {
            "data_source_id": kb_ds_id,
            "page_size": 100,
            "filter": {
                "property": relation_prop,
                "relation": {"contains": target_id},
            },
        }
        if cursor:
            kw["start_cursor"] = cursor
        r = cast(dict[str, Any], notion_client.data_sources.query(**kw))
        results.extend(r.get("results", []))
        if not r.get("has_more"):
            break
        cursor = r.get("next_cursor")
        if not cursor:
            break
    return results


def _replace_relation(
    relations: list[dict[str, Any]],
    merge_id_norm: str,
    canonical_id: str,
) -> list[dict[str, Any]]:
    """Relation 配列内の merge_id を canonical_id に置換（重複除去）."""
    canonical_norm = _normalize_id(canonical_id)
    new_relation: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in relations:
        rid = r.get("id", "")
        rid_norm = _normalize_id(rid)
        if rid_norm == merge_id_norm:
            # canonical にすり替え（後段で追加なので一旦スキップ）
            continue
        if rid_norm in seen:
            continue
        seen.add(rid_norm)
        new_relation.append({"id": rid})
    if canonical_norm not in seen:
        new_relation.append({"id": canonical_id})
    return new_relation


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=str)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--kind", type=str, default=None)
    parser.add_argument("--sleep", type=float, default=0.3)
    args = parser.parse_args()

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        print(f"CSV が見つかりません: {csv_path}", flush=True)
        return 2

    notion_client = NotionClient(auth=settings.notion_api_token)
    kb_db = cast(
        dict[str, Any],
        notion_client.databases.retrieve(database_id=settings.notion_db_knowledge_entry),
    )
    kb_ds_id = cast(str, kb_db["data_sources"][0]["id"])

    clusters = _read_csv(csv_path)
    print(f"クラスタ総数: {len(clusters)}", flush=True)
    print(f"DRY RUN: {args.dry_run}", flush=True)

    summary: dict[str, dict[str, int]] = defaultdict(
        lambda: {"clusters": 0, "merged_entries": 0, "kb_updated": 0, "skipped_N": 0}
    )

    for cid, cluster in clusters.items():
        kind = cluster["kind"]
        if args.kind and kind != args.kind:
            continue
        if cluster["approve"] != "Y":
            summary[kind]["skipped_N"] += 1
            continue
        canonical = cluster["canonical"]
        merges = cluster["merges"]
        if not canonical or not merges:
            continue

        canonical_name, canonical_id = canonical
        rel_props = _KB_RELATION_PROPS.get(kind, [])
        if not rel_props:
            print(f"  [{cid}] kind={kind} の Relation プロパティ未定義、スキップ", flush=True)
            continue

        summary[kind]["clusters"] += 1
        print(
            f"\n[{cid}] {kind}: canonical={canonical_name!r}, merges={len(merges)}",
            flush=True,
        )

        for merge_name, merge_id in merges:
            merge_id_norm = _normalize_id(merge_id)
            # canonical と同一なら何もしない（CSV のミスケア）
            if merge_id_norm == _normalize_id(canonical_id):
                continue

            # 各 Relation プロパティを走査
            affected_kb: list[tuple[dict[str, Any], str]] = []
            for rel_prop in rel_props:
                try:
                    pages = _find_kb_referencing(
                        notion_client, kb_ds_id, rel_prop, merge_id
                    )
                except Exception as e:
                    print(
                        f"    ⚠ 参照検索失敗 prop={rel_prop} merge={merge_name!r}: "
                        f"{type(e).__name__}: {str(e)[:80]}",
                        flush=True,
                    )
                    continue
                affected_kb.extend((p, rel_prop) for p in pages)

            print(
                f"  - {merge_name!r} → {canonical_name!r} | KB 影響件数: {len(affected_kb)}",
                flush=True,
            )

            if args.dry_run:
                summary[kind]["merged_entries"] += 1
                summary[kind]["kb_updated"] += len(affected_kb)
                continue

            # KB エントリの Relation を更新
            updated_count = 0
            for kb_page, rel_prop in affected_kb:
                props = kb_page.get("properties", {}) or {}
                rel_arr = (props.get(rel_prop) or {}).get("relation") or []
                new_rel = _replace_relation(rel_arr, merge_id_norm, canonical_id)
                try:
                    notion_client.pages.update(
                        page_id=kb_page["id"],
                        properties={rel_prop: {"relation": new_rel}},
                    )
                    updated_count += 1
                except Exception as e:
                    print(
                        f"    ⚠ KB 更新失敗 page={kb_page['id']}: "
                        f"{type(e).__name__}: {str(e)[:80]}",
                        flush=True,
                    )
                time.sleep(args.sleep)

            # マスタエントリを archive
            try:
                notion_client.pages.update(page_id=merge_id, archived=True)
            except Exception as e:
                print(
                    f"    ⚠ archive 失敗 {merge_name!r}: {type(e).__name__}: {str(e)[:80]}",
                    flush=True,
                )
            summary[kind]["merged_entries"] += 1
            summary[kind]["kb_updated"] += updated_count
            print(
                f"    → KB {updated_count} 件更新、archived: {merge_name!r}",
                flush=True,
            )
            time.sleep(args.sleep)

    print("\n=== サマリ ===", flush=True)
    for kind, s in summary.items():
        print(
            f"  {kind:8s}: clusters={s['clusters']} "
            f"merged_entries={s['merged_entries']} "
            f"kb_updated={s['kb_updated']} skipped_N={s['skipped_N']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
