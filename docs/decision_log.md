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

## [2026-05-10] Phase 順序変更：Slack 連携を先行、検証フェーズを後回し

- **背景**: 久保田様より「土壌 R&D の知見整理を最優先」「Slack `400-bg-rd-method` を AI 検索可能にしてほしい」との要望。Phase 1 検証フェーズ（プロンプト調整、表記揺れ正規化）を Slack 取り込みの後にスライド
- **作業順序**:
  1. KB DB スキーマ拡張（Slack 関連 3 プロパティ） ✅
  2. 本文 2000 字超過時のページ本体ブロック分割 ✅
  3. Slack Reader / Pipeline / 取り込みスクリプト ✅
  4. Slack 全期間バッチ取り込み（実施中）
  5. マスタ DB セマンティックマージ（MTG＋Slack の全エンティティに対して 1 回で実施）
  6. 久保田様による検証
  7. プロンプト調整・補正
- **影響**: マスタ DB の表記揺れ整理は Slack 取り込み後にまとめて 1 回で済む

---

## [2026-05-10] KB DB スキーマ拡張（Slack 連携）

- **追加プロパティ**:
  - `Slackチャンネル` (rich_text): チャンネル名（例: `400-bg-rd-method`）
  - `Slackスレッド ts` (rich_text): スレッドの ts。同一スレッドでグルーピング可能
  - `スレッド親メッセージ` (Self-Relation): 返信メッセージから親メッセージの KB エントリへの片方向参照
- **冪等適用済み**（既存 5 DB は破壊変更なし）

---

## [2026-05-10] 本文 2000 字超過時のページ本体ブロック分割

- **背景**: 既存の rich_text 切り詰めでは本文が完全保存されない。今後の Drive PDF や長文 Slack スレッドで全文保存が必要
- **採用**:
  - **本文（補完済み）／本文（原文）のいずれかが 2000 UTF-16 単位を超える場合のみ** ページ本体に分割保存
  - 短い本文は rich_text プロパティのみで完結（API コール削減）
  - rich_text には先頭スニペット + `...（続きはページ本体）` マーカーを格納
  - チャンク分割は改行境界優先、UTF-16 安全
  - UPDATE 時は既存の子ブロックを全削除してから再追加
- **影響**: `src/loaders/notion_writer.py` 大幅拡張。動作確認済（馬場さんMTG、本文 4646字 → heading + 3 paragraphs ＋ heading + 2 paragraphs = 7 ブロック）

---

## [2026-05-11] Slack `400-bg-rd-method` 全期間取り込み完了

- **対象**: チャンネル `400-bg-rd-method` (id `C081KJZ67DX`、private、メンバー 10)
- **規模**: 約 2,139 メッセージ（トップレベル 320 + 返信約 1,819）、期間 2024-11-17〜2026-05-10（約 18 ヶ月）
- **結果**: **2,124 件取り込み成功**（初回 2,121 + リトライ 3）、SKIP 18（既存 4 + subtype 14、channel_join 等）、FAIL 0（最終）
- **コスト**: 1 メッセージ 約 $0.007、合計 ≒ $15（当初見積 $55-85 から大幅減；メッセージが短かったため）
- **所要時間**: 約 12 時間（バックグラウンド実行）
- **解決した不具合**:
  - `prime_thread_parents` の無限ループバグ（`cursor=None` でも while True が抜けない）→ `if not r.get("has_more"): break` を追加
  - 初期化処理の Notion API タイムアウトでバッチ全体が落ちる問題 → スクリプト側で try/except でガード
- **影響**: KB DB が 898 → 3,024 エントリに増加。Slack スレッドはメッセージ単位で取り込み、`スレッド親メッセージ` Self-Relation で親子を辿れる

---

## [2026-05-11] マスタ DB セマンティックマージ完了

- **背景**: MTG Minutes DB 868 件 + Slack 2,124 件の取り込みで人/企業/プロジェクト/タグの表記揺れが多数発生（人 935、企業 2,073、プロジェクト 1,623、タグ 1,972）。検索品質向上のため一括正規化
- **採用アプローチ**:
  1. **Stage 1 Discover**: マスタ DB 全件を名前ソート → 60件オーバーラップ15のバッチ → Haiku 4.5 で重複判定 → CSV 出力
  2. **EXACT クラスタ**: 正規化（敬称・全角空白・末尾「社」「株式会社」等を除去）で完全一致するもの
  3. **AI クラスタ**: Haiku が「同一エンティティ」と判定したもの
  4. **canonical 選択**: 最も短い名前を採用（敬称なし・素形を優先）
  5. **自己矛盾フィルタ** (`scripts/filter_merge_proposals.py`): Haiku が reason に「別エンティティ」「異なる概念」等を書きながらマージ提案する事象が頻発したため、reason をパターンマッチして自動 approve=N にする後処理
  6. **Stage 2 Apply**: CSV を読んで KB エントリの Relation を canonical に付け替え + マスタエントリを archive
- **strict プロンプト**: タグ/プロジェクト で過剰マージが多かった（例: `LCA ← LCA手法/LCA算出/LCA評価`）ため、より保守的な判定基準を持つ別プロンプトを追加して再生成
- **結果**:
  - 提案 698 クラスタ → 自動却下フィルタ後 **502 クラスタ承認**
  - **635 マスタエントリ archive、2,115 KB エントリ Relation 更新**
  - 人 935→819 (-12%) / 企業 2,073→1,931 (-7%) / プロジェクト 1,623→1,517 (-7%) / タグ 1,972→1,902 (-4%)
- **コスト**: Haiku ≒ $1-2（discover）、Notion API のみ（apply）
- **新規ファイル**:
  - `src/processors/entity_deduplicator.py`（lenient/strict プロンプト 2 種）
  - `scripts/discover_master_db_merges.py`（CSV 出力）
  - `scripts/filter_merge_proposals.py`（自動却下フィルタ）
  - `scripts/apply_master_db_merges.py`（実マージ、idempotent）
- **既知の課題**:
  - `東北農研 → 東北大` のような疑わしいマージが少数残存（Notion 上で人手手戻しが必要）
  - canonical を「最も短い名前」で固定したため、業務的には別の正式名称を採用したいケースがあれば人手で再変更が必要
  - 残った重複クラスタ（互いに canonical が異なる）は再 discover ＋ 再 apply で対応可能
- **影響**: 検索時の重複ヒットが大幅減、関連先・関連プロジェクト Relation で同一エンティティに集約される

---

## [2026-05-10] Slack 連携（メッセージ単位取り込み）の設計と実装

- **取り込み単位**: 1 Slack メッセージ = 1 KB エントリ
  - 親メッセージと返信は別エントリ
  - 返信は `スレッド親メッセージ` Self-Relation で親に紐付け
- **Source URL**: Slack permalink（メッセージごとに一意）
- **External Key**: SHA256(source_url + occurred_at)
- **Source Type**: `Slack` (既存 enum)
- **本文構成**: text（メンション/チャンネル/リンク展開済み） + リアクション + 添付ファイル一覧
- **ノイズ除外**: subtype が `channel_join` 等のシステムメッセージは SKIP
- **投稿者の自動人マスタ登録**: 投稿者の Slack 表示名を「人」マスタに UPSERT し、関係者 Relation に追加
- **チャンネル名タグ自動付与**: `#<channel-name>` をタグ DB に登録し、内容タグ Relation に追加
- **対象チャンネル**: `400-bg-rd-method` (id: `C081KJZ67DX`、private、メンバー 10)
- **規模**: トップレベル 320 + 返信約 1,819 = 約 2,139 メッセージ、期間 2024-11-17〜2026-05-10
- **実測コスト**: 1 メッセージ ~$0.007、合計 推定 $15（短いメッセージが多いため当初見積 $55-85 から大幅減）
- **新規ファイル**: `src/sources/slack_reader.py`、`src/pipelines/slack_to_kb.py`、`scripts/ingest_slack_channel.py`、`scripts/check_slack_progress.py`

---

## [2026-05-10] MTG Minutes DB 868 件のバッチ取り込み完了

- **背景**: 2026-05-09 から開始した 868 件のバッチが 2026-05-10 早朝に完了
- **結果**:
  - 851 件 OK 新規 + 6 件再リトライで OK = 計 857 件取り込み成功
  - 11 件 SKIP（3 既存 + 8 空本文）
  - 6 件失敗（5 件は Notion API の transient 障害=タイムアウト/502、1 件はバグ）
  - 1 件のバグ修正後の再リトライで全 6 件成功
- **修正したバグ**: `_rich_text` の文字数カウントを Python `len`（code point）から **UTF-16 code unit** に変更（`src/loaders/notion_writer.py` と `src/loaders/master_db_writer.py`）。Notion API は UTF-16 code unit でカウントするため、サロゲートペア（絵文字や CJK 拡張 B 等）を含む 2000 文字直前の本文で 1 文字オーバーする事象が発生していた
- **最終 DB 件数**:
  - ナレッジエントリDB: 898 件
  - 人DB: 878 / 企業・団体DB: 2073 / プロジェクトDB: 1328 / タグDB: 1101
- **マスタ DB の重複多発について**: 表記揺れ（例: BG/BG社/BG株式会社）が別エントリとして大量作成されている。これは当初の「正規化は人手運用に委ねる」方針通りで、久保田様のフィードバックを得てから正規化スクリプトを検討する
- **影響**: Phase 1 のコア取り込み機能は完了。次は久保田様による検証フェーズ

---

## [2026-05-09] MTG Minutes DB を取り込み源泉に確定、Phase 1 拡張処理を実装

- **背景**: 久保田様より「メモは MTG Minutes DB（id=62b461da16f94c5abe673f6127fdc856）にまとまっている」と共有を受け、本 DB 配下 868 ページを取り込み源泉として確定。前回バッチで search API ヒューリスティックにより取り込んだ 40 件は、本 DB とは別個のページであった
- **採用**:
  - エンティティ抽出（`src/processors/entity_extractor.py`、Haiku 4.5、JSON 出力）
  - タグ生成（`src/processors/tagger.py`、Haiku 4.5、`name + category` ペア）
  - 主述補完（`src/processors/rewriter.py`、Sonnet 4.x、本文 30〜10000 字をリライト）
  - マスタ DB UPSERT（`src/loaders/master_db_writer.py`、初回全件 index 化＋ name キーで冪等作成）
  - パイプラインを `KnowledgeIngestionPipeline` クラス化（バッチで master cache を共有）
  - `NotionWriter` を Relation プロパティ書き込みに対応
  - バッチスクリプト `scripts/ingest_mtg_minutes_db.py`（`--skip-existing` でチェックポイント、`--limit/--offset/--pages` で部分実行可能）
- **接続解除済み 2 件のクリーンアップ**: `20240418_Governance` (`794932...`) と `20240722_Board MTG` の旧版 (`6530c0...`) を archive
- **既知の課題**:
  - 「社長」「弁護士」のような役職が人名として抽出されることがある（プロンプト改善の余地）
  - 表記揺れ（BG/BG社/BG株式会社）は正規化しない方針（マスタ側で人手運用）
  - 本文 2000 字超は依然末尾切り詰め（タスク #4 として残存）
- **影響**: Phase 1 の主要 4 タスク（要約・エンティティ・タグ・主述補完）が揃い、KB DB+マスタ4DB に Relation 付きで取り込めるようになった

---

## 未確定事項（T1〜T10）

以下は基本設計書セクション1に挙げた打ち合わせでの確認事項です。Phase 1以降の実装着手前に確定が必要です。

| # | 項目 | 状態 | 必要となるフェーズ |
|---|---|---|---|
| T1 | Notion AIアドオン導入の可否 | 未確定 | Phase 4（検索強化時） |
| T2 | Slack同期対象チャンネル | **暫定確定**: `400-bg-rd-method` を 2026-05-10 に取り込み済 | Phase 3 |
| T3 | プライベートチャンネル含むか | **暫定確定**: 含む（`400-bg-rd-method` がプライベート） | Phase 3 |
| T4 | 責任者・編集者・閲覧者の氏名とロール | 未確定 | Phase 0（権限設計） |
| T5 | Google Drive同期対象フォルダ範囲 | 未確定 | Phase 2 |
| T6 | Meet文字起こしの自動保存設定状況 | 未確定 | Phase 2 |
| T7 | 過去データの遡及範囲 | 未確定 | Phase 1（初期取り込み） |
| T8 | クライアント企業名等の機微情報マスキング要否 | 未確定 | Phase 1（加工処理） |
| T9 | GitHubリポジトリ名・Organization名 | **暫定確定**: `bg-d-katsuyama/bg_knowledge-base`（リポジトリ名のタイポ要確認） | Phase 0 |
| T10 | BGの会計処理上、米ドル決済が可能か | 未確定 | 課金開始時 |

---

## 現在のフェーズ

**Phase 1（Notion 内完結 + Slack `400-bg-rd-method` 取り込み）コア実装完了、検証フェーズ待ち**

### 現在の Notion DB 件数（2026-05-11 マージ後）

- ナレッジエントリDB: **3,024**
- 人DB: **819**
- 企業・団体DB: **1,931**
- プロジェクトDB: **1,517**
- タグDB: **1,902**

### Phase 0 残タスク

- [ ] T4・T7・T8 の確定（次回久保田様との打ち合わせ）
- [ ] GCPプロジェクト作成、サービスアカウント発行（Phase 2 で必要）
- [ ] Secret Manager 初期設定（Phase 2 で必要）

### 次のステップ（次セッション以降）

- [ ] **久保田様による検証**（最優先）— Notion 標準検索 / Claude.ai MCP で土壌 R&D 知見が引けるか確認
- [ ] 検証結果に基づくプロンプト調整（要約・エンティティ・タグ・リライト）
- [ ] 疑わしい誤マージの手戻し（例: `東北農研 → 東北大`）— Notion 上で archive を解除
- [ ] 残った重複クラスタの再 discover + 再 apply（必要なら）
- [ ] 既存 search 経由 38 件（旧 40 件 - archive 2 件）への #1〜#3 適用要否
- [ ] Slack Bot 化（`/kb-*` コマンド）— Phase 3
- [ ] Drive 連携（Phase 2、GCP セットアップから）

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
- [x] **接続解除済み 2 件の KB アーカイブ** （2026-05-09）
- [x] **#1 エンティティ抽出 / #2 タグ生成 / #3 主述補完 の実装** （2026-05-09）
- [x] **マスタ DB UPSERT ローダー実装** （2026-05-09、人/企業/プロジェクト/タグ）
- [x] **動作確認 3 件成功** （2026-05-09、MTG Minutes DB の先頭 3 件）
- [x] **MTG Minutes DB 868 件のバッチ取り込み完了** （2026-05-10、計 857 件成功）
- [x] **UTF-16 truncate バグ修正 + 失敗 6 件再処理** （2026-05-10、全成功）
- [x] **KB DB スキーマ拡張（Slack 連携 3 プロパティ）** （2026-05-10）
- [x] **本文 2000 字超過対応（ページ本体ブロック分割、UTF-16 安全）** （2026-05-10）
- [x] **Slack Reader / Pipeline / バッチスクリプト実装** （2026-05-10）
- [x] **Slack `400-bg-rd-method` 全期間取り込み（+2,124 件、KB→3,024）** （2026-05-10〜11）
- [x] **マスタ DB セマンティックマージ（502 クラスタ承認、635 archive、2,115 KB Relation 更新）** （2026-05-11）
  - 人 935→819 / 企業 2,073→1,931 / プロジェクト 1,623→1,517 / タグ 1,972→1,902