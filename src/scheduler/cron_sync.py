"""Cloud Scheduler から呼ばれる定期実行エントリポイント（スケルトン）.

日次バッチで全ソースの同期を実行する。

実装は Phase 1 で追加する（最初は Notion のみ）。
"""

from __future__ import annotations


def main() -> None:
    """Cloud Run Jobs のエントリポイント."""
    raise NotImplementedError("Phase 1 で実装予定")


if __name__ == "__main__":
    main()
