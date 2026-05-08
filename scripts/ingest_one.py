"""指定された 1 ページを Phase 1 パイプラインで取り込むスクリプト.

実行方法:
    uv run python scripts/ingest_one.py <notion_page_id>

例:
    uv run python scripts/ingest_one.py 6530c0ed-4701-47e1-bacb-8da2deb10679
"""

from __future__ import annotations

import sys

from src.common.logger import get_logger
from src.common.models import SourceType
from src.pipelines.notion_to_kb import ingest_notion_page

logger = get_logger(__name__)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) != 2:
        print("usage: uv run python scripts/ingest_one.py <notion_page_id>", file=sys.stderr)
        return 2

    page_id = sys.argv[1].strip()
    try:
        kb_page_id, created = ingest_notion_page(page_id, source_type=SourceType.MANUAL)
    except Exception as e:
        logger.error("ingest_failed", page_id=page_id, error=str(e))
        return 1

    action = "created" if created else "updated"
    print(f"\n[OK] KB エントリを {action} しました: {kb_page_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
