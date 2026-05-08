# 設計判断記録（Decision Log）

本ファイルは、本プロジェクトで行った設計上の選択を時系列で記録します。Claude Code が自動更新する場合と、開発者が手動で追記する場合の両方があります。

各エントリは以下の形式で記載します。

```
## [YYYY-MM-DD] 短いタイトル
- **背景**: なぜこの判断が必要になったか
- **選択肢**: 検討した選択肢
- **採用**: 採用した選択肢と理由
- **影響**: この判断が及ぼす影響範囲
```

---

## [2026-04-24] 基本設計書 v0.1 を作成

- **背景**: BG社のナレッジが断片化しており、構造化検索可能な基盤が必要
- **選択肢**: 既存ツール導入 vs 自社実装
- **採用**: Notion + Claude API + GCP の自社実装。理由はBG固有の業務ドメイン（土壌・LCA・クレジット等）に対応した加工が必要なため
- **影響**: `docs/architecture.md` に詳細

---

## [2026-04-24] CLAUDE.md の配置をプロジェクトルートに変更

- **背景**: 基本設計書 v0.1 では `.claude/CLAUDE.md` の配置だったが、Claude Code は標準でプロジェクトルートの `CLAUDE.md` を自動読み込みする
- **選択肢**:
  1. 設計書通り `.claude/CLAUDE.md` に配置
  2. プロジェクトルートに配置（標準慣例）
- **採用**: (2) プロジェクトルート配置
- **理由**: Claude Code の標準動作に合わせることで、追加設定なしに自動認識される
- **影響**: `.claude/` ディレクトリには Claude Code のスキル・メモリ・設定のみ配置

---

## [2026-04-24] Phase 0 スキャフォールドを生成

- **背景**: Claude Code での実装着手のため、リポジトリの初期構造を整備
- **採用内容**:
  - `pyproject.toml`（Python 3.12 / uv / ruff / pytest / mypy strict）
  - 全層の `__init__.py` とモジュールスケルトン
  - `src/common/config.py` および `src/common/secrets.py` の実装
  - `.env.example` / `.gitignore` / `CLAUDE.md` / `README.md`
  - GitHub Actions の CI ワークフロー
- **影響**: Phase 0 の残タスクは GCPプロジェクト作成・Secret Manager初期化・Notionスキーマ手動構築

---

## [2026-05-08] 既存ドキュメント不可侵を **不変条件（Invariant）** として確定

- **背景**: Phase 1 着手前、勝山様より「既存ドキュメントは絶対に編集・削除しない」前提の明示的確認があった。本プロジェクトは「既存メモを参照→ KB 配下に整理」が目的であり、ソース側へ書き戻すパスは設計上存在しない
- **不変条件**:
  - 取り込み元（Notion 既存ページ・DB、Drive、Slack 等）への **書き込み API は呼ばない**
  - 書き込み先は常に `NOTION_PARENT_PAGE_ID` 配下の 5 DB に限定
  - ソース側へのアクセスは **読み取りのみ**
  - 既存ドキュメントへの読み取り対象拡張（Integration 接続追加）は、毎回事前に勝山様に確認する
- **適用範囲**: 全フェーズ（Phase 1〜4）。本不変条件は CLAUDE.md §7 と整合
- **影響**: `src/sources/` 層は読み取り専用。書き込みは `src/loaders/` のみが担当し、書き込み先は KB 配下に限定

---

## [2026-05-08] Notion API 2025-09-03 仕様（data_sources）への対応

- **背景**: 5DB 構築スクリプトの初回実行で、`databases.create` に `properties` を直接渡しても無視され、デフォルトの「Name」タイトルだけのデータソースが生成される事象が発生
- **原因**: Notion API は 2025-09-03 リリースで「データベース」と「データソース」の中間層を導入。`notion-client` v3.0.0 はその新仕様で動作しており、プロパティは `initial_data_source.properties` に包んで渡す必要がある
- **採用**:
  - 新規 DB 作成: `databases.create(initial_data_source={"properties": {...}})`
  - 既存 DB へのプロパティ追加・リネーム: `data_sources.update(data_source_id=..., properties={...})`
  - Relation 参照先: `database_id` から `data_source_id` へ移行
  - `pages.create` の親指定も `{"type": "data_source_id", ...}` 形式を採用
- **影響**: `src/loaders/schema_manager.py`、`src/loaders/notion_writer.py` で data_sources API ベースの実装を採用。既存 5 DB は再実行で正しいスキーマに自動修正済み（DB ID は不変）

---

## [2026-05-08] Phase 1 最小エンドツーエンドパイプライン実装

- **背景**: Phase 0 完了後、Phase 1（Notion 既存メモ → ナレッジエントリ DB の取り込み）を着手。本日のゴールは **取り込みパイプラインを最初の 1 件で動作確認** すること
- **採用構成**:
  - `src/sources/notion_reader.py`: 指定ページのプロパティ・本文を再帰抽出（toggle 等の入れ子も最大3階層まで）
  - `src/processors/summarizer.py`: Claude Sonnet 4.x による 3〜5 行の日本語要約。プロンプトキャッシング対応
  - `src/loaders/notion_writer.py`: 外部キー（SHA256(source_url + occurred_at)）による UPSERT
  - `src/pipelines/notion_to_kb.py`: 上記 3 層をオーケストレート
  - `scripts/ingest_one.py`: 1 件取り込み用 CLI
  - `scripts/ingest_memo_candidates.py`: ヒューリスティックでスコア付与したメモ候補を一括取り込み
- **既知の限界（今後のタスク）**:
  - エンティティ抽出（人/企業/プロジェクト）未実装 → 関連 Relation は埋まらない
  - タグ生成未実装 → 内容タグは空
  - 主述補完未実装 → 本文（補完済み）は原文と同一
  - 本文 2000 文字超過時は末尾切り詰め（ページ本体ブロックへの分割は未実装）
- **影響**: Phase 1 の続きはエンティティ抽出・タグ生成・主述補完の各処理を順次追加していく

---

## 未確定事項（T1〜T10）

以下は基本設計書セクション1に挙げた打ち合わせでの確認事項です。Phase 1以降の実装着手前に確定が必要です。

| # | 項目 | 状態 | 必要となるフェーズ |
|---|---|---|---|
| T1 | Notion AIアドオン導入の可否 | 未確定 | Phase 4（検索強化時） |
| T2 | Slack同期対象チャンネル | 未確定 | Phase 3 |
| T3 | プライベートチャンネル含むか | 未確定 | Phase 3 |
| T4 | 責任者・編集者・閲覧者の氏名とロール | 未確定 | Phase 0（権限設計） |
| T5 | Google Drive同期対象フォルダ範囲 | 未確定 | Phase 2 |
| T6 | Meet文字起こしの自動保存設定状況 | 未確定 | Phase 2 |
| T7 | 過去データの遡及範囲 | 未確定 | Phase 1（初期取り込み） |
| T8 | クライアント企業名等の機微情報マスキング要否 | 未確定 | Phase 1（加工処理） |
| T9 | GitHubリポジトリ名・Organization名 | **暫定確定**: `bg-d-katsuyama/bg_knowledge-base`（リポジトリ名のタイポ要確認） | Phase 0 |
| T10 | BGの会計処理上、米ドル決済が可能か | 未確定 | 課金開始時 |

---

## 現在のフェーズ

**Phase 1（Notion 内完結の取り込み）進行中**

### Phase 0 残タスク

- [ ] T4・T7・T8 の確定（次回久保田様との打ち合わせ）
- [ ] GCPプロジェクト作成、サービスアカウント発行（Phase 2 で必要）
- [ ] Secret Manager 初期設定（Phase 2 で必要）

### Phase 1 残タスク

- [ ] エンティティ抽出処理の実装（人/企業/プロジェクト Relation を埋める）
- [ ] タグ候補生成処理の実装（内容タグ Relation を埋める）
- [ ] 主述補完処理の実装（本文（補完済み）に書き込む）
- [ ] 本文 2000 文字超過対応（ページ本体ブロックへの分割）
- [ ] 久保田様による検証（Notion 標準検索 or Claude.ai 経由 MCP で KB に質問）
- [ ] 検証結果に基づく要約プロンプトの調整
- [ ] 取り込み対象拡大（残り約 6,000 ページのうち価値あるもの）

### 完了タスク

- [x] GitHubリポジトリ作成
- [x] リポジトリ初期スキャフォールド生成（2026-04-24）
- [x] uv.lock 生成と CI 動作確認（2026-05-03）
- [x] Lintルール調整（日本語docstring対応、Enum/datetime近代化）
- [x] **Notion スキーマ 5 DB 構築（API 経由で冪等的に）** （2026-05-08）
- [x] **Notion API + Anthropic API 接続テスト** （2026-05-08）
- [x] **Phase 1 最小エンドツーエンドパイプライン実装** （2026-05-08）
- [x] **既存メモ 1 件の取り込み試験** （2026-05-08, `20240722_Board MTG`）
- [x] **メモ候補 106 件のバッチ取り込み** （2026-05-08, $3〜8 想定）