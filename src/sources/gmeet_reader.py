"""Google Meet 文字起こしリーダー（スケルトン）.

実装方針:
- Workspace設定で文字起こしが所定フォルダに自動保存される前提
- 当該フォルダを監視（毎時実行）
- 新規ファイル検出 → テキスト取得 → パイプラインへ

実装は Phase 2 で追加する。
"""

from __future__ import annotations

# TODO(Phase 2): Meet 文字起こし読み取り実装
