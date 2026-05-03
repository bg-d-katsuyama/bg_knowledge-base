"""Notion 既存メモ → ナレッジエントリDB のパイプライン（スケルトン）.

Phase 1 のメインスクリプト。

処理フロー:
1. Notion APIで既存ミーティングメモDBを読み取り
2. 各ページのIDと最終更新日時を記録
3. 未処理／更新ありのページのみClaude APIへ
4. Claudeに：要約／タグ候補／エンティティ抽出／主述補完を依頼
5. 人DB・企業DB・タグDBへのUPSERT
6. ナレッジエントリDBへ新規行を作成

実装は Phase 1 で追加する。
"""

from __future__ import annotations

# TODO(Phase 1): エンドツーエンドのパイプラインを実装


def main() -> None:
    """エントリポイント（CLIから呼ぶ用）."""
    raise NotImplementedError("Phase 1 で実装予定")


if __name__ == "__main__":
    main()
