# BG Knowledge Base

BG社のナレッジ（ミーティングメモ、Google Meet議事録、Drive文書、Slackメッセージ）を一元化し、構造化検索可能なナレッジベースとしてNotion上に構築する社内システムです。

## ドキュメント

- [基本設計書](docs/architecture.md) — 必読
- [Notionスキーマ詳細](docs/schema.md)
- [運用手順](docs/runbook.md)
- [設計判断履歴](docs/decision_log.md)
- [APIコスト記録](docs/api_cost_tracking.md)

## クイックスタート（開発者向け）

### 1. 前提条件

- Python 3.12 以上
- [uv](https://docs.astral.sh/uv/) インストール済み（後述）
- Git
- GCP/Notion/Slackの認証情報（`.env.example` 参照）

### 2. uv のインストール

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 3. リポジトリのセットアップ

```bash
git clone https://github.com/bg-d-katsuyama/bg_knowledge-base.git
cd bg_knowledge-base

# 環境変数ファイルを作成
cp .env.example .env
# → .env を編集し、必要な値を設定

# 依存関係のインストール（開発用ツールも含む）
uv sync --extra dev
```

### 4. 動作確認

```bash
# テスト実行
uv run pytest

# Lint
uv run ruff check src tests

# 型チェック
uv run mypy src
```

## Claude Code での開発

本リポジトリは [Claude Code](https://docs.claude.com/en/docs/claude-code) を主たる開発エージェントとして利用する前提で構成されています。

```bash
# プロジェクトルートで Claude Code を起動
claude
```

Claude Code は起動時に [`CLAUDE.md`](./CLAUDE.md) を自動で読み込みます。プロジェクト固有のコーディング規約・ディレクトリ構成・確認が必要な操作などが記載されています。

## ライセンス

本リポジトリは社内利用限定（Proprietary）です。
