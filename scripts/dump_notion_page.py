"""指定 Notion ページの本文をローカルにダンプする読み取り専用スクリプト.

Anthropic API は使わない。Notion API の読み取りのみ。
ダンプ結果を Claude Code（人手抽出）がそのまま読めるよう UTF-8 テキストで保存する。

実行方法:
    uv run python scripts/dump_notion_page.py <page_id> [--out logs/notion_page_dump.txt]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from notion_client import Client as NotionClient

from src.common.config import settings
from src.sources.notion_reader import NotionReader


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("page_id")
    parser.add_argument("--out", default="logs/notion_page_dump.txt")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    notion = NotionClient(auth=settings.notion_api_token)
    reader = NotionReader(notion)
    doc = reader.read_page(args.page_id)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        f"# {doc.title}\n"
        f"URL: {doc.source_url}\n"
        f"last_edited: {doc.last_edited_time.isoformat()}\n"
        f"body_chars: {len(doc.body)}\n"
        f"{'=' * 60}\n\n"
        f"{doc.body}\n",
        encoding="utf-8",
    )
    print(f"タイトル: {doc.title}")
    print(f"本文文字数: {len(doc.body)}")
    print(f"出力: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
