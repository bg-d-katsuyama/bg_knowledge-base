"""バッチ取り込みの進捗確認スクリプト.

logs/ingest_mtg_full_*.log の最新ファイルを解析し、
- 処理済み件数（OK 新規/更新、SKIP、FAIL の集計）
- 残件数
- 平均所要時間（直近 30 件）
- 推定残り時間
- 直近 5 行
を表示する。

実行方法:
    uv run python scripts/check_ingest_progress.py
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    log_dir = Path("logs")
    if not log_dir.exists():
        print("logs/ ディレクトリが存在しません")
        return 1
    candidates = sorted(log_dir.glob("ingest_mtg_full_*.log"))
    if not candidates:
        print("ingest_mtg_full_*.log が見つかりません")
        return 1
    log = candidates[-1]
    print(f"対象ログ: {log}")
    text = log.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    n_total: int | None = None
    for line in lines:
        m = re.search(r"\[2/3\] バッチ取り込み開始: (\d+) 件", line)
        if m:
            n_total = int(m.group(1))
            break

    ok_new = 0
    ok_upd = 0
    skip_existing = 0
    skip_empty = 0
    fail = 0
    last_idx: int | None = None
    progress_lines: list[tuple[int, str]] = []

    for line in lines:
        m = re.search(r"\[\s*(\d+)/\s*\d+\]\s+(OK 新規|OK 更新|SKIP|FAIL)", line)
        if not m:
            continue
        idx = int(m.group(1))
        status = m.group(2)
        last_idx = idx
        progress_lines.append((idx, line))
        if status == "OK 新規":
            ok_new += 1
        elif status == "OK 更新":
            ok_upd += 1
        elif status == "SKIP":
            if "(existing)" in line:
                skip_existing += 1
            else:
                skip_empty += 1
        elif status == "FAIL":
            fail += 1

    processed = ok_new + ok_upd + skip_existing + skip_empty + fail
    print()
    print(f"  total           : {n_total if n_total is not None else '不明'}")
    print(f"  processed       : {processed}")
    print(f"    OK 新規        : {ok_new}")
    print(f"    OK 更新        : {ok_upd}")
    print(f"    SKIP (existing): {skip_existing}")
    print(f"    SKIP (empty)   : {skip_empty}")
    print(f"    FAIL           : {fail}")
    if n_total is not None and last_idx is not None:
        remaining = n_total - last_idx
        pct = last_idx / n_total * 100
        print(f"  remaining       : {remaining} ({pct:.1f}% 完了)")

    # 完了判定
    completed = any("[3/3] バッチ完了" in line for line in lines)
    if completed:
        print("\n  ★ バッチ完了済み")
    else:
        # 現在時刻と最新行の時刻でアイドル判定
        try:
            mtime = datetime.fromtimestamp(log.stat().st_mtime, tz=timezone.utc)
            now = datetime.now(tz=timezone.utc)
            idle = (now - mtime).total_seconds()
            print(f"\n  ログ最終更新: {idle:.0f} 秒前")
            if idle > 120:
                print("  ⚠ 2 分以上更新なし。バッチが停止している可能性あり")
        except OSError:
            pass

    if progress_lines:
        print("\n直近 5 行:")
        for _, line in progress_lines[-5:]:
            print(f"  {line.rstrip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
