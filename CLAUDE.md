# CLAUDE.md — BG Knowledge Base 開発ガイド

> **このファイルはClaude Codeが毎セッションで最初に読み込む指示書です。**
> 編集する際は影響範囲を慎重に検討し、`docs/decision_log.md` に記録してください。

---

## 1. プロジェクト概要

BG社のナレッジ（ミーティングメモ、Google Meet議事録、Drive文書、Slackメッセージ）を一元化し、構造化検索可能なナレッジベースとしてNotion上に構築する社内システム。Phase 1〜4まで段階的に実装します。詳細は `docs/architecture.md` を必ず参照してください。

**主たる利用者**:
- 責任者（Slack経由で同期コマンド実行・運用判断）
- スタッフ（Notion上で日常的に検索・参照）
- 勝山（開発・保守、Claude Code利用者）

---

## 2. 必読ドキュメント

実装着手前に、以下を必ず参照してください。

| ファイル | 内容 |
|---|---|
| `docs/architecture.md` | 基本設計書（最重要・正） |
| `docs/schema.md` | Notionスキーマ詳細 |
| `docs/runbook.md` | 運用手順 |
| `docs/decision_log.md` | 設計判断の履歴 |
| `docs/api_cost_tracking.md` | Claude API使用量・コスト記録 |

---

## 3. 開発環境

- **Python**: 3.12 以上
- **パッケージ管理**: [uv](https://docs.astral.sh/uv/)（pip ではなく uv を使用）
- **リンター/フォーマッタ**: ruff
- **テスト**: pytest
- **型チェック**: mypy（strict モード）

### よく使うコマンド

```bash
# 依存関係のインストール
uv sync

# 開発用依存も含めてインストール
uv sync --extra dev

# 新しい依存を追加
uv add <package-name>
uv add --dev <package-name>      # 開発用

# テスト実行
uv run pytest
uv run pytest tests/unit         # 単体テストのみ
uv run pytest -m "not slow"      # 遅いテストをスキップ

# リント・フォーマット
uv run ruff check src tests       # lint
uv run ruff check --fix src tests # 自動修正
uv run ruff format src tests      # フォーマット

# 型チェック
uv run mypy src

# スクリプトの実行例
uv run python -m src.pipelines.notion_to_kb
```

---

## 4. ディレクトリ構成と各層の責務

```
src/
├── sources/      # データソース別リーダー（Notion/Drive/Meet/Slack の生データ取得）
├── processors/   # Claude APIによる加工（要約・タグ付け・主述補完・エンティティ抽出）
├── loaders/      # Notionへの書き込み（スキーマ管理・UPSERT）
├── pipelines/    # ソース別の取り込みパイプライン（sources → processors → loaders）
├── bot/          # Slack Bot（Events API受け、コマンドハンドラ）
├── scheduler/    # Cloud Schedulerから呼ばれる定期実行エントリポイント
└── common/       # 共通基盤（設定/認証/ロガー/モデル/シークレット）
```

**設計原則**:
- 各層は単方向に依存（`pipelines → sources/processors/loaders → common`）
- `common` は他層のいずれにも依存しない
- 外部APIアクセスは必ず該当する `sources/` または `loaders/` 経由で行う
- ビジネスロジックは `processors/` と `pipelines/` に集約

---

## 5. コーディング規約

- **型ヒント必須**: 全関数の引数・戻り値に型ヒントを付ける
- **Pydantic v2**: データモデルは `src/common/models.py` の Pydantic BaseModel を継承
- **構造化ログ**: `print` ではなく `src/common/logger.py` の structlog ロガーを使用
- **設定**: 環境変数は `src/common/config.py` の `Settings` 経由でのみ参照（直接 `os.getenv` を呼ばない）
- **シークレット**: 本番では Secret Manager から取得（`src/common/secrets.py`）。ローカルでは `.env` ファイル
- **リトライ**: 外部API呼び出しは `tenacity` で指数バックオフを実装
- **docstring**: 全公開関数・クラスに Google スタイルの docstring を付ける
- **エラーハンドリング**: 例外は具体的な型で捕捉。`except Exception` は最上位の境界以外では避ける

---

## 6. 触ってはいけないファイル

以下のファイル・ディレクトリは**人間の確認なしに編集しない**でください。

- `.env` — 実シークレットを含む
- `service-account*.json`, `*.pem`, `*.key` — 認証情報
- `infra/` 配下の本番マニフェスト — 本番リソースに直接影響
- `.github/workflows/deploy.yml` — 本番デプロイ設定
- `docs/architecture.md` — 設計の正本（変更時は必ず勝山に確認）

---

## 7. 確認が必要な操作

以下の操作を実行する前に、**必ずユーザーに確認**を取ってください。

- 本番Notionデータベースへの書き込み・スキーマ変更
- Secret Manager の値追加・変更・削除
- Cloud Run / Cloud Scheduler の本番デプロイ
- Claude API への大量呼び出し（推定$10以上）
- Google Drive / Slack のスコープ拡大
- 既存テーブルのマイグレーション
- `docs/architecture.md` の変更

---

## 8. 実装フェーズ

現在のフェーズと残タスクは `docs/decision_log.md` 末尾の「現在のフェーズ」を参照してください。

| Phase | 内容 | 主要マイルストーン |
|---|---|---|
| 0 | 環境構築 | GCPプロジェクト作成、Secret Manager初期化、Notionスキーマ5DB構築 |
| 1 | Notion内完結 | 既存メモを新スキーマに取り込む単発スクリプト |
| 2 | Drive / Meet連携 | サービスアカウント連携、定期同期 |
| 3 | Slack連携 | Bot構築、`/kb-*` コマンド |
| 4 | 運用定着 | 検索強化・ダッシュボード・監査ログレビュー |

---

## 9. Claude Code 作業時の自己ルール

1. **不明点は推測せず質問する**: 仕様が曖昧な箇所は実装を進める前にユーザーに確認
2. **一度に大きすぎる変更をしない**: 1コミット = 1論理変更
3. **テストを書く**: 新規モジュールには最低限の単体テストを同時作成
4. **判断を記録する**: 設計上の選択を行った場合 `docs/decision_log.md` に追記
5. **コストを意識する**: Claude API を呼ぶ実装時は使用モデル・推定コストをコメントに記載
6. **既存コードのスタイルに合わせる**: 新規ファイルでも既存の規約（型ヒント、docstring、ログ）を踏襲

---

## 10. トラブル時の連絡先

- 開発・保守: 勝山様（GitHub: bg-d-katsuyama）
- 運用責任者: 久保田様
- インシデント時は Slack `@kb-admins` ユーザーグループに連絡
