"""discover_master_db_merges.py が出力した CSV に対して、
理由欄に自己矛盾（「別エンティティ」等）を含むクラスタを自動 approve=N にするフィルタ.

Haiku の出力で「これは別エンティティだが」と言いながらマージ提案する事象が
頻発するため、reason をパターンマッチして自動却下するセーフティネット。

実行方法:
    uv run python scripts/filter_merge_proposals.py path/to/proposals.csv
    # 上書き保存される。元 CSV は .bak で保存。

オプション:
    --keep-original     : .bak バックアップを保存せず上書き
    --output PATH       : 別ファイルに出力（指定しない場合は上書き）
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

# 自己矛盾を示す reason テキストのキーワード
_REJECTION_PATTERNS = [
    r"別エンティティ",
    r"別概念",
    r"別判定",
    r"別工程",
    r"別の?対象",
    r"別の?プロセス",
    r"別フェーズ",
    r"異なる(エンティティ|概念|工程|主体|対象|プロセス|フェーズ)",
    r"は異なる",
    r"マージしない",
    r"分離(推奨|を推奨|してください)",
    r"独立した",
    r"再検討",
    r"再評価",
    r"親会社と子会社",
    r"全体と一部",
    r"部門",
    r"修飾(語|だけ)",
    r"修飾",
]
_REJECTION_RE = re.compile("|".join(_REJECTION_PATTERNS))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=str)
    parser.add_argument("--keep-original", action="store_true")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    src = Path(args.csv_path)
    if not src.exists():
        print(f"CSV が見つかりません: {src}")
        return 2

    # 入力 CSV を読み込み
    with src.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if "approve" not in fieldnames:
        print("approve 列がありません。CSV フォーマットを確認してください。")
        return 1

    # クラスタ単位で reason をチェックし、approve を変更
    cluster_status: dict[str, str] = {}  # cluster_id → 'Y' or 'N'
    for row in rows:
        cid = row.get("cluster_id", "")
        reason = row.get("reason", "")
        # EXACT クラスタは絶対残す
        if "EXACT" in cid:
            cluster_status[cid] = "Y"
            continue
        # 既に N なら維持
        if cluster_status.get(cid) == "N":
            continue
        if _REJECTION_RE.search(reason):
            cluster_status[cid] = "N"
        else:
            cluster_status.setdefault(cid, "Y")

    # 適用
    auto_rejected = 0
    for row in rows:
        cid = row.get("cluster_id", "")
        new_approve = cluster_status.get(cid, row.get("approve", "Y"))
        if new_approve == "N" and (row.get("approve", "Y") or "Y").upper() == "Y":
            auto_rejected += 1
        row["approve"] = new_approve

    # 出力
    if args.output:
        out = Path(args.output)
    else:
        if not args.keep_original:
            bak = src.with_suffix(src.suffix + ".bak")
            src.rename(bak)
            print(f"  バックアップ: {bak}")
        out = src

    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    n_clusters = len(cluster_status)
    n_y = sum(1 for v in cluster_status.values() if v == "Y")
    n_n = n_clusters - n_y
    print(f"  クラスタ総数: {n_clusters}")
    print(f"  approve=Y   : {n_y}")
    print(f"  approve=N   : {n_n} (うち今回自動却下: {auto_rejected} 行)")
    print(f"  出力: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
