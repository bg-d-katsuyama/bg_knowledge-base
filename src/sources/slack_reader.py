"""Slack メッセージリーダー（スケルトン）.

実装方針:
- Events API でメッセージ受信
- スレッド単位で1エントリ化
- 1時間更新がなければ確定処理
- ファイル添付メタ情報を保持

実装は Phase 3 で追加する。
"""

from __future__ import annotations

# TODO(Phase 3): Slack スレッド読み取り実装
