"""Slack チャンネル → KB DB のバッチ取り込みスクリプト.

実行方法:
    # 動作確認（最も新しい N 件のみ）
    uv run python scripts/ingest_slack_channel.py --channel-name 400-bg-rd-method --limit 4

    # 全期間取り込み
    uv run python scripts/ingest_slack_channel.py --channel-name 400-bg-rd-method

    # 既存KB エントリをスキップして再開
    uv run python scripts/ingest_slack_channel.py --channel-name 400-bg-rd-method --skip-existing

オプション:
    --channel-name STR   : チャンネル名（# なし）。--channel-id と排他
    --channel-id STR     : チャンネル ID（C0XXXX...）。--channel-name と排他
    --limit N            : 取り込む最大メッセージ数（古い順）
    --skip-existing      : 既に取り込み済み（同じ source_url）をスキップ
    --no-entity          : エンティティ抽出を無効化
    --no-tag             : タグ生成を無効化
    --no-revise          : 主述補完を無効化
    --sleep SEC          : 各メッセージ処理後の sleep 秒（既定 0.3）

備考:
    - 推定コスト: 2,139 件 × ~$0.03 = $55-85（フル機能）
    - 親メッセージを先に処理する順序を保証（SlackReader が古い順 → 親→返信で yield）
    - 失敗したメッセージは続行し、サマリで報告
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
from slack_sdk import WebClient

from src.common.config import settings
from src.common.logger import get_logger
from src.pipelines.slack_to_kb import SlackKnowledgeIngestionPipeline

logger = get_logger(__name__)


def _resolve_channel_id(client: WebClient, name: str) -> str | None:
    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "types": "public_channel,private_channel",
            "limit": 200,
        }
        if cursor:
            kwargs["cursor"] = cursor
        r = cast(dict[str, Any], client.conversations_list(**kwargs))
        for ch in r.get("channels", []):
            if ch.get("name") == name:
                return cast(str, ch["id"])
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return None


def _list_existing_slack_source_urls(notion_client: NotionClient, channel_name: str) -> set[str]:
    """KB DB の既存エントリのうち、指定チャンネルの source_url 集合を返す."""
    db_id = settings.notion_db_knowledge_entry
    db = cast(dict[str, Any], notion_client.databases.retrieve(database_id=db_id))
    ds_id = cast(str, db["data_sources"][0]["id"])
    urls: set[str] = set()
    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "data_source_id": ds_id,
            "page_size": 100,
            "filter": {
                "property": "Slackチャンネル",
                "rich_text": {"equals": channel_name},
            },
        }
        if cursor:
            kwargs["start_cursor"] = cursor
        r = cast(dict[str, Any], notion_client.data_sources.query(**kwargs))
        for row in r.get("results", []):
            props = row.get("properties", {}) or {}
            url = (props.get("ソースURL") or {}).get("url") or ""
            if url:
                urls.add(_normalize_slack_url(url))
        cursor = r.get("next_cursor") if r.get("has_more") else None
        if not cursor:
            break
    return urls


def _normalize_slack_url(url: str) -> str:
    """Slack permalink を比較用に正規化（query parameters の順序で揺れないよう）."""
    try:
        u = urlparse(url)
    except Exception:
        return url
    return f"{u.scheme}://{u.netloc}{u.path}"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--channel-name", type=str, default=None)
    g.add_argument("--channel-id", type=str, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--no-entity", action="store_true")
    parser.add_argument("--no-tag", action="store_true")
    parser.add_argument("--no-revise", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.3)
    args = parser.parse_args()

    pipeline = SlackKnowledgeIngestionPipeline(
        enable_entity_extraction=not args.no_entity,
        enable_tagging=not args.no_tag,
        enable_body_revision=not args.no_revise,
    )

    if args.channel_id:
        channel_id = args.channel_id
    else:
        cid = _resolve_channel_id(pipeline.slack_client, args.channel_name)
        if not cid:
            print(f"channel '{args.channel_name}' が見つかりません", flush=True)
            return 2
        channel_id = cid
    meta = pipeline.reader.get_channel_meta(channel_id)
    channel_name = cast(str, meta.get("name") or channel_id)

    print(f"[1/3] チャンネル: #{channel_name} (id={channel_id})", flush=True)
    print(
        f"      モード: entity={not args.no_entity} tag={not args.no_tag} "
        f"revise={not args.no_revise} skip_existing={args.skip_existing}",
        flush=True,
    )

    existing_urls: set[str] = set()
    if args.skip_existing:
        print("[1.5/3] 既存 KB の source_url を取得中...", flush=True)
        try:
            existing_urls = _list_existing_slack_source_urls(pipeline.notion_client, channel_name)
            print(f"      → 既存: {len(existing_urls)}", flush=True)
        except Exception as e:
            print(
                f"      ⚠ 既存取得に失敗（取り込みは継続）: {type(e).__name__}: {str(e)[:120]}",
                flush=True,
            )
        # スレッド親 KB ID をプリロード（失敗してもバッチは継続）
        try:
            primed = pipeline.prime_thread_parents(channel_id)
            print(f"      → スレッド親プリロード: {primed}", flush=True)
        except Exception as e:
            print(
                f"      ⚠ プリロード失敗（取り込みは継続、同一バッチ内で親→子は解決可能）: "
                f"{type(e).__name__}: {str(e)[:120]}",
                flush=True,
            )

    print("[2/3] メッセージ取り込み開始", flush=True)
    success_new = 0
    success_upd = 0
    skipped_existing = 0
    skipped_subtype = 0
    failed = 0
    processed = 0

    for msg in pipeline.reader.iter_messages(channel_id, sleep_between_pages=args.sleep):
        if args.limit is not None and processed >= args.limit:
            break

        title_snip = (
            (msg.text_resolved or "(添付のみ)").strip().splitlines()[0][:50]
            if (msg.text_resolved or msg.files)
            else "(no text)"
        )
        marker = "↳" if msg.parent_ts else " "

        if args.skip_existing:
            normalized = _normalize_slack_url(msg.permalink)
            if normalized in existing_urls:
                skipped_existing += 1
                processed += 1
                print(
                    f"  [{processed:5d}] {marker} SKIP (existing) | {title_snip}",
                    flush=True,
                )
                continue

        try:
            result = pipeline.ingest_message(msg)
            processed += 1
            if result is None:
                skipped_subtype += 1
                print(
                    f"  [{processed:5d}] {marker} SKIP (subtype/empty) | {title_snip}",
                    flush=True,
                )
                continue
            if result.created:
                success_new += 1
                action = "新規"
            else:
                success_upd += 1
                action = "更新"
            print(
                f"  [{processed:5d}] {marker} OK {action} | "
                f"P{result.n_people} O{result.n_organizations} "
                f"Pj{result.n_projects} T{result.n_tags} "
                f"body {result.body_chars_original}->{result.body_chars_revised} | "
                f"{title_snip}",
                flush=True,
            )
        except Exception as e:
            failed += 1
            processed += 1
            print(
                f"  [{processed:5d}] {marker} FAIL | {title_snip} | {type(e).__name__}: {str(e)[:120]}",
                flush=True,
            )
            traceback.print_exc()
        time.sleep(args.sleep)

    print("\n[3/3] バッチ完了", flush=True)
    print(f"  success_new      : {success_new}", flush=True)
    print(f"  success_upd      : {success_upd}", flush=True)
    print(f"  skipped_existing : {skipped_existing}", flush=True)
    print(f"  skipped_subtype  : {skipped_subtype}", flush=True)
    print(f"  failed           : {failed}", flush=True)
    print(f"  processed total  : {processed}", flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    # 未使用の re をリンタ回避用に touch
    _ = re
    sys.exit(main())
