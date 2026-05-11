"""マスタDB（人/企業/プロジェクト/タグ）の重複候補を Haiku で検出するスクリプト.

Stage 1（本スクリプト）: 重複候補を CSV に出力
Stage 2（apply_master_db_merges.py）: 人手承認後、CSV を読んで実マージ

実行方法:
    # 全マスタDB を一括検査
    uv run python scripts/discover_master_db_merges.py

    # 1 種類だけ
    uv run python scripts/discover_master_db_merges.py --kind 人

    # バッチサイズを変更
    uv run python scripts/discover_master_db_merges.py --batch-size 50 --overlap 10

オプション:
    --kind {人,企業・団体,プロジェクト,タグ,all}  : 対象（既定 all）
    --batch-size N    : 1 バッチに含める名前数（既定 60）
    --overlap N       : 隣接バッチでオーバーラップさせる件数（既定 15、再現率向上）
    --output PATH     : 出力 CSV パス（既定 logs/master_db_merge_proposals_<ts>.csv）

備考:
    - 出力 CSV はそのまま久保田様/勝山様で確認・編集してから apply スクリプトで適用
    - コスト目安: 6694 件 × Haiku 4.5 = 約 $2-3
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from anthropic import Anthropic
from notion_client import Client as NotionClient

from src.common.config import settings
from src.common.logger import get_logger
from src.processors.entity_deduplicator import EntityDeduplicator

logger = get_logger(__name__)


KINDS = {
    "人": ("notion_db_people", "氏名"),
    "企業・団体": ("notion_db_organization", "名称"),
    "プロジェクト": ("notion_db_project", "プロジェクト名"),
    "タグ": ("notion_db_tag", "タグ名"),
}


def _normalize_for_sort(name: str) -> str:
    """ソート用の正規化（似た名前を近接させる）."""
    s = name.strip().lower()
    # 全角空白→半角
    s = s.replace("　", " ")
    # 末尾の社名・敬称を一旦削って近接化
    for suffix in (
        "株式会社",
        "(株)",
        "（株）",
        "社",
        "ホールディングス",
        "Inc.",
        "Inc",
        "Corp.",
        "Corp",
        "ltd",
        "Ltd",
        "さん",
        "様",
        "氏",
        "先生",
    ):
        if s.endswith(suffix.lower()):
            s = s[: -len(suffix)].rstrip()
            break
    return s


def list_db_entries(client: NotionClient, db_id: str) -> list[tuple[str, str]]:
    """DB 全件を `[(name, page_id), ...]` で返す."""
    db = cast(dict[str, Any], client.databases.retrieve(database_id=db_id))
    ds = cast(str, db["data_sources"][0]["id"])
    entries: list[tuple[str, str]] = []
    cursor: str | None = None
    while True:
        kw: dict[str, Any] = {"data_source_id": ds, "page_size": 100}
        if cursor:
            kw["start_cursor"] = cursor
        r = cast(dict[str, Any], client.data_sources.query(**kw))
        for row in r.get("results", []):
            props = row.get("properties", {}) or {}
            name = ""
            for prop in props.values():
                if prop.get("type") == "title":
                    name = "".join(t.get("plain_text", "") for t in (prop.get("title") or []))
                    break
            if name:
                entries.append((name, row["id"]))
        if not r.get("has_more"):
            break
        cursor = r.get("next_cursor")
        if not cursor:
            break
    return entries


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--kind",
        choices=[*KINDS.keys(), "all"],
        default="all",
    )
    parser.add_argument("--batch-size", type=int, default=60)
    parser.add_argument("--overlap", type=int, default=15)
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--sleep", type=float, default=0.3)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="より保守的なプロンプトで過剰マージを抑制（タグ/プロジェクト推奨）",
    )
    args = parser.parse_args()

    notion_client = NotionClient(auth=settings.notion_api_token)
    anthropic_client = Anthropic(api_key=settings.anthropic_api_key)
    dedup = EntityDeduplicator(
        client=anthropic_client,
        model=settings.anthropic_model_haiku,
        max_output_tokens=2000,
        enable_prompt_caching=settings.claude_prompt_caching_enabled,
    )

    if args.output:
        out_path = Path(args.output)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path("logs") / f"master_db_merge_proposals_{ts}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    target_kinds = list(KINDS.keys()) if args.kind == "all" else [args.kind]

    rows_to_write: list[dict[str, str]] = []
    cluster_id_seq = 0

    for kind in target_kinds:
        settings_attr, _title_prop = KINDS[kind]
        db_id = getattr(settings, settings_attr)
        if not db_id:
            print(f"[{kind}] DB ID 未設定。スキップ", flush=True)
            continue

        print(f"\n=== {kind} ===", flush=True)
        entries = list_db_entries(notion_client, db_id)
        print(f"  DB 件数: {len(entries)}", flush=True)
        if len(entries) < 2:
            continue
        # ソートで近接化
        entries.sort(key=lambda x: _normalize_for_sort(x[0]))
        names = [e[0] for e in entries]
        ids = [e[1] for e in entries]

        # まず完全一致で先にマージ候補化（プロンプト消費削減）
        seen_norm: dict[str, list[int]] = {}
        for i, name_i in enumerate(names):
            key = _normalize_for_sort(name_i)
            seen_norm.setdefault(key, []).append(i)
        # EXACT で構築済のクラスタ（後段の AI 重複検出用）
        seen_pairs: set[frozenset[int]] = set()
        for _key, indices in seen_norm.items():
            if len(indices) >= 2:
                cluster_id_seq += 1
                cid = f"{kind}-EXACT-{cluster_id_seq}"
                # canonical: 最も短い名前を採用（敬称や肩書きを取り除いた素形を優先）
                # 長さ同順なら名前のソート順で安定化
                indices_sorted = sorted(indices, key=lambda i: (len(names[i]), names[i]))
                canon = indices_sorted[0]
                seen_pairs.add(frozenset(indices))
                rows_to_write.append(
                    {
                        "kind": kind,
                        "cluster_id": cid,
                        "role": "canonical",
                        "name": names[canon],
                        "page_id": ids[canon],
                        "reason": "正規化で完全一致",
                    }
                )
                for j in indices_sorted[1:]:
                    rows_to_write.append(
                        {
                            "kind": kind,
                            "cluster_id": cid,
                            "role": "merge",
                            "name": names[j],
                            "page_id": ids[j],
                            "reason": "正規化で完全一致",
                        }
                    )

        # 残りエントリでバッチ処理
        n = len(names)
        step = max(1, args.batch_size - args.overlap)
        n_batches = max(1, (n + step - 1) // step)
        print(f"  Haiku バッチ実行: {n_batches} batches (size={args.batch_size}, overlap={args.overlap})", flush=True)
        for bi, start in enumerate(range(0, n, step), 1):
            end = min(n, start + args.batch_size)
            batch_names = names[start:end]
            try:
                result = dedup.detect_merges(kind, batch_names, strict=args.strict)
            except Exception as e:
                print(
                    f"  [{bi}/{n_batches}] FAIL: {type(e).__name__}: {str(e)[:120]}",
                    flush=True,
                )
                continue
            if not result.merges:
                continue
            for prop in result.merges:
                # ローカルインデックスをグローバルインデックスへ
                ai_canon_global = start + prop.canonical_index
                merge_globals = [start + i for i in prop.merge_indices]
                all_globals = [ai_canon_global, *merge_globals]
                cluster_set = frozenset(all_globals)
                if cluster_set in seen_pairs:
                    continue
                seen_pairs.add(cluster_set)

                # canonical を「最も短い名前」に再選定（AI の選択は ignore）
                all_globals_sorted = sorted(
                    all_globals, key=lambda i: (len(names[i]), names[i])
                )
                canon_global = all_globals_sorted[0]
                merge_only = [i for i in all_globals_sorted[1:]]

                cluster_id_seq += 1
                cid = f"{kind}-AI-{cluster_id_seq}"
                rows_to_write.append(
                    {
                        "kind": kind,
                        "cluster_id": cid,
                        "role": "canonical",
                        "name": names[canon_global],
                        "page_id": ids[canon_global],
                        "reason": prop.reason,
                    }
                )
                for j in merge_only:
                    rows_to_write.append(
                        {
                            "kind": kind,
                            "cluster_id": cid,
                            "role": "merge",
                            "name": names[j],
                            "page_id": ids[j],
                            "reason": prop.reason,
                        }
                    )
            print(
                f"  [{bi}/{n_batches}] OK ({len(result.merges)} merges proposed, total clusters={cluster_id_seq})",
                flush=True,
            )
            time.sleep(args.sleep)

    # CSV 出力
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["kind", "cluster_id", "role", "name", "page_id", "reason", "approve"],
        )
        writer.writeheader()
        for row in rows_to_write:
            row_with_approve = {**row, "approve": "Y"}
            writer.writerow(row_with_approve)

    print("\n=== 完了 ===", flush=True)
    print(f"  クラスタ数: {cluster_id_seq}", flush=True)
    print(f"  出力 CSV: {out_path}", flush=True)
    print("  確認: CSV を開いて、approve 列で 'Y'/'N' を編集", flush=True)
    print("  N にしたクラスタは apply スクリプトでスキップされます", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
