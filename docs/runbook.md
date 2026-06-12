# 運用手順書（Runbook）

本ドキュメントは BG Knowledge Base の**現行運用（ローカル完結方式）**の手順をまとめたものです。

> **注**: GCP / Cloud Run / Slack Bot 前提の旧方式は 2026-05-29 の方針転換（`docs/decision_log.md` 参照）で廃止されました。
> 旧版の Runbook が必要な場合は git 履歴を参照してください。

---

## 1. 現行運用の全体像

- **目的**: Google Meet 議事録（docx）やマニュアル等から土壌 R&D の知見を抽出し、マスターデータ（xlsx → スプレッドシート）として整備する
- **方式**: 外部 API 課金ゼロ・ローカル完結。Claude Code が手元のファイルを直接読み、知見抽出から xlsx 生成までを行う
- **Notion**: 読み取り専用。現行運用では Notion への書き込みは一切行わない
- **使用しないもの**: GCP / Drive API / Sheets API / Anthropic API（従量課金なし。Claude のサブスクリプション内で動作）

### 日常運用の流れ

1. Google Drive から新しい議事録（.docx）をダウンロード
2. `data/drive_input/` に配置
3. Claude Code に知見抽出を依頼（→ `logs/insights_drive.json` に蓄積、`output/` に xlsx 生成）
4. xlsx の内容を確認し、マスターデータのスプレッドシートへ転記

非エンジニア向けの詳細手順（環境構築含む）は **「BGナレッジベース_セットアップ手順書_久保田様向け」**（Word・v1.0・2026-06-12）を参照してください。

---

## 2. 体制（移行期間・併走運用）

| 役割 | 担当 |
|---|---|
| 運用責任者 | 久保田様 |
| 開発・保守、運用サポート | 勝山様（GitHub: bg-d-katsuyama） |

2026-06 より移行期間として、**勝山様・久保田様の両名が操作可能**です。併走中のルール：

1. 作業を始める前に Slack 等で「今から KB 作業をします」と一声かける
2. 作業の最初に `git pull`、最後に `docs/decision_log.md` への記録 + コミット + プッシュを行う
3. Notion トークンは各自専用のものを使い、共有しない（久保田様用は読み取り権限のみで発行）
4. 判断に迷ったら手を止めて勝山様に連絡する

---

## 3. 定常作業：新規議事録の追補抽出

Claude Code への依頼ベースで行います（依頼文の定型はセットアップ手順書 第12〜13章を参照）。

1. 新しい docx を `data/drive_input/` に置く
2. Claude Code を起動し、以下を順に依頼する
   - 「git pull して最新の状態にしてください」
   - 「data/drive_input の新規ファイル『（ファイル名）.docx』から土壌R&Dの知見を抽出し、既存知見（logs/insights_drive.json）と統合した xlsx を output に生成してください。Notion への書き込みは行わないでください」
3. `output/` に生成された xlsx を開いて内容を確認する（おかしい行は Claude Code に修正を依頼）
4. マスターデータのスプレッドシートへ転記する
5. 「今回の作業内容を docs/decision_log.md に記録して、コミット・プッシュしてください」と依頼する

**関連スクリプト**（Claude Code が内部で使用）：

| スクリプト | 役割 |
|---|---|
| `scripts/dump_docx.py` | docx をテキスト化 |
| `scripts/dump_notion_page.py` | Notion ページのテキスト化（マニュアル等の抽出時） |
| `scripts/build_master_data.py` | 知見 JSON から xlsx / csv を生成 |

対応ファイル形式は docx。pdf / pptx が必要になったら `uv add pypdf python-pptx` で追加します。

---

## 4. データの置き場所

| パス | 内容 | git 管理 |
|---|---|---|
| `data/drive_input/` | 取り込み元の議事録 docx | 対象外（ローカルのみ） |
| `logs/insights_drive.json` | 抽出済み知見の蓄積（正） | 対象外（ローカルのみ・要バックアップ） |
| `logs/insights.json`, `logs/insights_all.json` | 過去の抽出中間ファイル | 対象外 |
| `output/` | 生成した xlsx / csv | 対象外（ローカルのみ） |
| `.env` | Notion トークン・DB ID | 対象外（共有・コミット禁止） |

**注意**: git 管理外のファイルは PC 間で自動共有されません。移行期間中、追補抽出は原則どちらか一人が担当し、`logs/insights_drive.json` が二重に育たないようにしてください（担当を交代する際はファイルを受け渡す）。

---

## 5. 定期作業

- 新規議事録が溜まったタイミングで追補抽出を実施（頻度は久保田様の判断）
- 四半期：権限の棚卸し（Notion インテグレーション・トークン / GitHub コラボレータ）

---

## 6. トラブル対応

| 症状 | 対処 |
|---|---|
| Notion で 401 / unauthorized エラー | `.env` のトークンを確認（前後の空白に注意）。インテグレーションが対象 DB に接続されているか確認。解決しなければトークン再発行 |
| `git pull` で conflict（競合） | そのまま触らず勝山様へ連絡（併走作業がぶつかった状態） |
| 抽出結果が明らかにおかしい | 元の docx の破損・文字化けを確認し、Claude Code に元ファイルとの突き合わせを依頼 |
| Claude Code が応答しない・挙動が変 | Esc で中断 → `/clear` で会話リセット → 直らなければ再起動 |

インシデント時の連絡先：勝山様（移行期間中）／久保田様

---

## 7. 完全移管時にやること（TODO）

移行期間を終えて久保田様の単独運用に切り替える際に実施します。

- [ ] 勝山様用 Notion トークン（インテグレーション）の無効化
- [ ] GitHub リポジトリの権限整理（BG 側アカウントへの移管、または久保田様の admin 化）
- [ ] `CLAUDE.md` と本 Runbook の体制・連絡先の更新
- [ ] `docs/decision_log.md` に移管完了を記録

---

## 8. 保留中の旧方式（参考）

Phase 2 当初の GCP / Cloud Run / Slack Bot 構成は 2026-05-29 の方針転換で廃止されました。Meet 自動連携・Slack Bot（`/kb-*` コマンド）は「必要になれば再検討」の保留扱いです（経緯は `docs/decision_log.md` を参照）。旧方式の運用手順・デプロイ手順は git 履歴上の本ファイル旧版にあります。
