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

## [2026-06-01] Drive 議事録 21 ファイルから 41 知見を抽出（ローカル完結）

- **背景**: 2026-05-29 方針（外部 API 課金ゼロ・ローカル完結）の本命タスク「`data/drive_input/` のローカルファイルを Claude Code が直接抽出」を実施。前回（マニュアル v1.3 → 22 知見）に続く 2 バッチ目
- **入力**: `data/drive_input/` に手動配置された 21 個の `.docx`
  - 大半が Gemini 議事録（BG｜R&D Discussion @Yutenji シリーズ、Gmeet メモ、堆肥製造の専門家 MTG）
  - 1 件は表中心の仕様書（`BG堆肥製造仕様書_千葉`）で抽出価値が低く、ほぼ除外
- **新規ファイル/依存**:
  - 🆕 `scripts/dump_docx.py` — `.docx` を段落＋表でテキスト化（python-docx のみ、Google API 不使用）。単一/`--all` 一括の 2 モード
  - `uv add python-docx`（保留していた docx 読み取り依存を確定）
- **抽出方針**: 土壌 R&D の技術・研究知見に焦点化。純粋なスケジュール調整・契約事務・解析自動化運用などのノイズは除外
- **成果**: 41 知見を `logs/insights_drive.json` に出力 → `output/soil_rd_master_drive_<ts>.xlsx`(+CSV) を生成
  - 領域分布: 微生物 17 / 堆肥 13 / その他 8 / モニタリング 2 / pH 1
  - 信頼度: 高 22 / 中 19、検証ステータス: 実証済み 18 / 検討中 23
  - 発言者・所属を実名で構造化（久保田隆星・大湖史朗・今村浩司・武部裕樹・瓜里聡＝BG、黒木要＝島本微生物工業、多武良彰＝バイオソイル、服部吉弘＝ララファーム）
- **設計判断**: v1.3 の 22 知見（承認済み `logs/insights.json`）とは**別ファイル**に分離。Drive バッチを単独 xlsx で久保田様/勝山様がレビューできるようにし、承認後に統合する想定（v1.3 が単独レビューされた流れを踏襲）
- **知見の中身（抜粋）**: 無害化基準 55℃×100 日、CN 比（露地 20 前後/ハウス 25〜30）、米ぬか vs 糖蜜の使い分け、二段階仕込みによる微生物リレー、バイオ液の完成基準（透明・pH7.5〜8.5）と希釈倍率 100〜300 倍、多様性指標（α=シャノン/β=距離）による土壌の物差し、PGPB の機能 3 分類、特許戦略（物の発明＋クレームずらし＋ダミー特許）、品質基準指標、温度・水分率の現場測定法
- **次回**: 勝山様→久保田様の xlsx レビュー。承認後に v1.3 分と統合した通し xlsx を生成。新規 Drive ファイル追加があれば同フローで追補
- **影響**: Phase 2（ローカル完結）の Drive 分マスターデータ初版が揃った

---

## [2026-05-28] GCP セットアップ方針：BG 勤務先アカウントでの個人 OAuth（案 A）

- **背景**: Phase 2 改訂版で必要な Drive API / Docs API / Sheets API の認証方式を決定する必要があった
- **選択肢**:
  1. サービスアカウント方式（BG GCP 組織での発行、フォルダ共有が必要）
  2. 個人 OAuth 方式（GCP プロジェクトを作成したアカウントの権限を流用）
- **採用**: (2) 個人 OAuth 方式
- **理由**:
  - 勝山様は BG 内で権限が制限されているため、久保田様 / Workspace 管理者との往復が多い方式は避けたい
  - 新スコープは「手動実行」前提なので、Cloud Run 等の自動化が不要 = サービスアカウントの長期運用メリットが薄い
  - 月額 $0、課金登録不要
- **重要な訂正**（同日中）:
  - 当初「個人 Google アカウント（Gmail）で進める」と案内したが、勝山様の指摘で誤りと判明
  - 個人 Gmail で GCP プロジェクトを作ると、BG Drive にアクセスできない（共有先に追加されていないため）
  - 正解: 勝山様の **BG 勤務先アカウント**（既に BG Drive にアクセスできているアカウント）で GCP プロジェクトを作る
  - BG Workspace ポリシーで GCP 作成が制限されていた場合の代替案: 個人 Gmail + 久保田様に共有追加依頼
- **影響**:
  - `docs/gcp_setup_personal_oauth.md` を作成（ステップバイステップ手順書、§0.5 にアカウント方針を明記）
  - `scripts/google_oauth_setup.py` を作成（初回認証 + Drive 接続テスト付き）
  - `.gitignore` に `.secrets/` を追加
  - `pyproject.toml` に `openpyxl` を追加（マスターデータ Excel 出力用、現時点未使用）

---

## [2026-05-28] マスターデータ粒度の確定：案 B（1 行 = 1 知見）

- **背景**: スプレッドシート出力の粒度として 3 案（A: 1 行 = 1 KB エントリ / B: 1 行 = 1 知見 / C: 2 シート分割）を比較
- **採用**: 案 B
- **理由**:
  - 久保田様の「マスターデータ」要望は、検索性・引用性の高い知見単位の構造化を強く示唆
  - 案 A はマスターデータ感が弱い（KB の鏡）、案 C は実装・運用が複雑
  - 案 B は Claude API コスト推定 $10〜30 で許容範囲
- **サンプル抽出結果**:
  - 5 KB エントリから 17 知見抽出（領域: 堆肥 5、微生物 2、モニタリング 5、その他 5）
  - 抽出品質は良好。発言者・所属・信頼度・検証ステータスまで構造化
  - 観察された論点: サンプルが Slack 由来に偏った / 業務進捗系（「資料更新が未完了」等）も抽出された → 久保田様判断ポイント
- **久保田様協議材料 4 点を準備**:
  1. `docs/master_data_proposal_for_kubota.md` — 協議文書本体
  2. `docs/master_data_schema.md` — 設計たたき台
  3. `docs/master_data_sample.md` — 17 知見の Markdown 表示
  4. `logs/master_data_sample_20260528_201850.csv` — CSV 形式
- **影響**: 本実装 (Task #16〜#18) は案 B のスキーマで進める

---

## [2026-05-28] 既存 KB の土壌関連エントリ規模調査

- **目的**: マスターデータの源泉となる土壌 R&D 関連エントリの規模感把握
- **手法**: タグ DB 全件 (1,902) から土壌関連キーワード 30 個でフィルタ → 該当タグの KB 紐付けをローカル集計
- **結果**:
  - 土壌関連タグ: 253 件
  - **土壌タグ付き KB（ユニーク）: 1,099 件（KB 3,024 件中の 36%）**
  - KB 紐付き延べ: 1,540
  - 主要タグ: 堆肥(256)、堆肥製造(146)、LCA(82)、土壌検査(74)、土壌(74)、土壌形成資材(69)、土作り(47)
- **詳細**: `logs/soil_tags_investigation_20260528_192835.csv`
- **影響**: スプレッドシート想定行数は 3,000〜8,000 行（1 KB エントリ平均 3〜7 知見の見込み）

---

## [2026-05-28] Phase 2 スコープ全面改訂：土壌 R&D マスターデータ作成へ

- **背景**: 2026-05-28 同日中、久保田様より新要望「汎用ナレッジベースではなく、土壌関連 R&D に絞ったマスターデータを **Google スプレッドシート** で作りたい」を受領。汎用 KB として運用する Phase 2/3 の前提が変わる
- **新スコープ**:
  - **対象**: 土壌 R&D 関連のみ
  - **入力**: (a) 既存 KB 3,024 件のうち土壌関連エントリ + (b) 新規取り込み対象の Notion ページ（要 URL 共有）+ (c) Google Drive 上の 1 フォルダ配下の doc ファイル
  - **出力**: Google スプレッドシート（マスターデータ）
  - **更新頻度**: 必要時に手動（Cloud Run/Scheduler 不要）
  - **スコープ外**: Meet 文字起こし連携、Slack Bot 化（Phase 3）— いずれも保留
- **アーキテクチャの変更点**:
  - Notion KB はデータ集約層として継続。**KB から土壌関連エントリを抽出 → Claude で構造化 → Sheets に書き込み** が新パイプライン
  - 既存パイプライン（`src/sources/notion_reader.py` / `src/sources/slack_reader.py` / `src/loaders/notion_writer.py` / processors 各種）は流用
  - 新規実装: `src/loaders/sheets_writer.py`、`src/processors/master_data_extractor.py`、`scripts/export_soil_rd_master.py`
  - Drive 取り込みは継続（doc ファイル特化、Meet は外す）
- **スキーマ未確定**: スプレッドシートの 1 行が「1 KB エントリ」か「1 知見/事実」かはたたき台を作成して久保田様と詰める。`docs/master_data_schema.md` に格納予定
- **GCP セットアップへの影響**: Cloud Run 不要なので軽量化。必要なのは Drive API + Sheets API + Secret Manager（サービスアカウント発行のため）のみ
- **影響**: タスク #8 (gmeet_reader.py) を削除。タスク #13〜#18 を追加（土壌タグ調査、スキーマたたき台、Sheets API セットアップ、sheets_writer、master_data_extractor、export スクリプト）

---

## [2026-05-28] Phase 1 検証フェーズ完了 + Phase 2 着手判断（T5〜T8 確定）

- **背景**: 2026-05-12 に久保田様へ共有した検証 1 巡目（白色腐朽菌／ミネラル多様性／クライミング効果）への回答について、2026-05-28 に久保田様より「これで OK」の回答を受領。Phase 1 検証フェーズはクローズ
- **Phase 0 残タスク T5〜T8 を確定**（2026-05-28 勝山様経由で受領）:
  - **T5 (Drive 同期対象フォルダ)**: **複数の特定フォルダ**（個別 ID は別途受領予定）
  - **T6 (Meet 文字起こしの自動保存)**: **設定済み（指定フォルダへ自動保存）**
  - **T7 (過去データ遡及範囲)**: **全期間（対象フォルダ内のすべて）**
  - **T8 (機微情報マスキング)**: **不要、そのまま Claude API へ送信**（Slack 取り込みと同方針）
- **次フェーズの決定**: Phase 2 (Drive/Meet 連携) に着手。Phase 3 (Slack Bot) と残務クリーンアップ（誤マージ手戻し等）は Phase 2 着地後に判断
- **Phase 2 着手の手順**:
  1. Drive/Meet 対象フォルダの具体 ID 受領
  2. GCP プロジェクト作成方針確定（BG アカウント or 個人）
  3. GCP セットアップ（プロジェクト・API 有効化・サービスアカウント・JSON 鍵）
  4. Drive 側でサービスアカウントを対象フォルダに「閲覧者」として共有（read-only 不変条件順守）
  5. `.env` 設定 + 接続テスト
  6. `src/sources/gdrive_reader.py`、`src/sources/gmeet_reader.py`、`src/pipelines/gdrive_to_kb.py`、`scripts/ingest_gdrive_folder.py` 実装
  7. 1 件 → 小規模 → 全期間バッチ取り込み
  8. 久保田様による検証
- **コスト見積**: 初期一括取り込み $80〜200（基本設計書 §10 準拠）。Slack 同様にメッセージ/ファイル単位で前後する
- **影響**: Phase 2 設計は基本設計書 §4.2 のとおり。`processors/` と `loaders/` は Phase 1 で完成したものを再利用

---

## [2026-05-29] Phase 2 再々改訂：外部 API 課金ゼロ・ローカル完結方式へ

- **背景**: 2026-05-29 久保田様と協議。前回（2026-05-28）の改訂版（GCP + Drive API + Sheets API + Anthropic API スクリプト）から、運用負荷とコストを下げる方向でさらに簡素化する要望
- **久保田様との合意事項**:
  1. **Drive 自動取り込みは保留** → GCP セットアップは不要。Drive ファイルは勝山様が手動ダウンロードしローカルフォルダに配置
  2. **知見抽出は Claude Code（対話セッション）が直接実施** → スクリプトからの Anthropic API 課金呼び出しは不要（案 1）
  3. **マスターデータのフォーマットは現行サンプル（`docs/master_data_sample.md` / 案 B＝1 行 1 知見）で承認**
  4. **Notion 源泉は当面 1 ページのみ**: 「腐植性堆肥製造マニュアル_v1.3」(`312be8e04eea8072aaf8e0b30c6a9b40`)。土壌タグ付き全 1,099 件の一括抽出は当面不要
- **外部 API 課金の扱い**:
  - ❌ Anthropic API（→ Claude Code が直接抽出）
  - ❌ Google Drive API / GCP / サービスアカウント（→ ローカルファイル手動配置）
  - ❌ Google Sheets API（→ ローカル xlsx/CSV を生成し、勝山様が手動でスプレッドシートへアップロード）
  - ✅ Notion 読み取りのみ存続（源泉ページ本文の取得。`src/sources/notion_reader.py` を流用）
- **新しいデータフロー**:
  ```
  源泉① Notion ページ（読み取り専用）── dump_notion_page.py でローカルにテキスト化
  源泉② data/drive_input/ のローカルファイル（手動配置）
        → Claude Code が直接「1 行 1 知見」を抽出 → logs/insights.json
        → build_master_data.py が承認済み列の xlsx/CSV を生成（output/）
        → 勝山様が手動で Google スプレッドシートへ取り込み
  ```
- **新規/役割変更したファイル**:
  - 🆕 `scripts/dump_notion_page.py` — Notion ページ本文をローカルダンプ（Anthropic 不使用、Notion 読みのみ）
  - 🆕 `scripts/build_master_data.py` — 知見 JSON → xlsx/CSV 整形（決定論的、openpyxl のみ）
  - 🆕 `data/drive_input/` — Drive 手動配置フォルダ（README 以外 gitignore）
  - 🆕 `output/` — マスターデータ成果物（gitignore）
- **廃止（旧改訂版で予定していたが不要になったもの）**: GCP セットアップ全般、`gdrive_reader.py`(Google API)、`gdrive_to_kb.py`、`sheets_writer.py`、`google_oauth_setup.py`、`docs/gcp_setup_personal_oauth.md`、`sample_master_data_output.py`(Anthropic API 版)。これらの物理削除は勝山様確認後に実施
- **初回成果**: 「腐植性堆肥製造マニュアル_v1.3」から 22 知見を抽出し `output/soil_rd_master_<ts>.xlsx`(+CSV) を生成。**2026-05-31 勝山様が xlsx を確認し「現時点で問題なし」と承認**（フォーマット・粒度・内容 OK）
- **次回**: Drive ファイル（`data/drive_input/` に手動配置）を同フローで追加抽出するのが本命タスク。ファイル形式に応じて pypdf / python-docx 等を `uv add`
- **影響**: Phase 2 は外部課金ゼロ・ローカル完結で運用可能に。Meet 連携・Slack Bot・Notion 全件抽出は引き続き保留

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
| T5 | Google Drive同期対象フォルダ範囲 | **確定**: 複数の特定フォルダ（具体 ID は受領待ち） | Phase 2 |
| T6 | Meet文字起こしの自動保存設定状況 | **確定**: 自動保存あり（指定フォルダ） | Phase 2 |
| T7 | 過去データの遡及範囲 | **確定**: 全期間（対象フォルダ内すべて） | Phase 2（初期取り込み） |
| T8 | クライアント企業名等の機微情報マスキング要否 | **確定**: 不要（そのまま Claude へ送信） | Phase 2（加工処理） |
| T9 | GitHubリポジトリ名・Organization名 | **暫定確定**: `bg-d-katsuyama/bg_knowledge-base`（リポジトリ名のタイポ要確認） | Phase 0 |
| T10 | BGの会計処理上、米ドル決済が可能か | 未確定 | 課金開始時 |

---

## 現在のフェーズ

**Phase 2 再々改訂版（土壌 R&D マスターデータ作成・外部 API 課金ゼロ・ローカル完結）進行中。Claude Code が `data/drive_input/` のローカルファイルから直接知見抽出 → xlsx 生成 → 勝山様が手動でスプレッドシートへ。GCP/Drive API/Sheets API/Anthropic API は全て不使用。Meet 連携と Slack Bot は保留**

### 現在の Notion DB 件数（2026-05-11 マージ後）

- ナレッジエントリDB: **3,024**
- 人DB: **819**
- 企業・団体DB: **1,931**
- プロジェクトDB: **1,517**
- タグDB: **1,902**

### Phase 0 残タスク

- [ ] T4 の確定（権限ロール、Phase 4 までに）
- ~~GCP プロジェクト作成・サービスアカウント・Secret Manager~~ → 2026-05-29 の再々改訂で**不要化**（ローカル完結方式）

### Phase 2 再々改訂版タスク（ローカル完結・進行中）

- [x] **マスターデータ形式を案 B（1 行 1 知見）で確定・久保田様承認** （2026-05-29）
- [x] **`scripts/dump_notion_page.py` / `scripts/build_master_data.py` 実装** （2026-05-29）
- [x] **マニュアル v1.3 → 22 知見抽出 → xlsx 生成 → 勝山様承認（現時点 OK）** （2026-05-31）
- [x] **`scripts/dump_docx.py` 実装 + python-docx 追加** （2026-06-01）
- [x] **Drive 議事録 21 ファイル → 41 知見抽出（`logs/insights_drive.json` → 単独 xlsx）** （2026-06-01）
- [ ] **Drive バッチ 41 知見の xlsx を勝山様→久保田様でレビュー**（最優先）
- [ ] 承認後、v1.3 22 件 + Drive 41 件を統合した通し xlsx を生成
- [ ] 旧 GCP/Sheets 方式の不要ファイル物理削除（勝山様確認後）: `scripts/google_oauth_setup.py`, `scripts/sample_master_data_output.py`, `scripts/export_master_data_sample_xlsx.py`, `scripts/investigate_soil_master.py`, `docs/gcp_setup_personal_oauth.md`
- [ ] 新規 Drive ファイル追加時の追補抽出（必要に応じて pypdf / python-pptx を `uv add`）
- [ ] （保留）既存 KB 3,024 件の土壌タグ付き 1,099 件からの一括抽出（当面不要との久保田様判断）

### Phase 2 完了後の候補（保留）

- [ ] Meet 文字起こし連携（必要になれば）
- [ ] Slack Bot 化（`/kb-*` コマンド）— Phase 3（必要になれば）
- [ ] 疑わしい誤マージの手戻し（例: `東北農研 → 東北大`）— Notion 上で archive を解除
- [ ] 残った重複クラスタの再 discover + 再 apply（必要なら）
- [ ] 既存 search 経由 38 件（旧 40 件 - archive 2 件）への #1〜#3 適用要否

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
- [x] **Phase 1 検証 1 巡目 久保田様 OK 回答受領、検証フェーズクローズ** （2026-05-28）
- [x] **T5/T6/T7/T8 確定** （2026-05-28、勝山様経由）