# スキル: Notion操作

Notion APIを使った操作を実装する際の指針。詳細なスキーマ定義は `docs/schema.md` を参照。

## 原則

- **必ず `notion-client` ライブラリを使用**: 自前で `requests` を書かない
- **スキーマ定義は一元管理**: 各DBのプロパティ名は `src/loaders/schema_manager.py` の定数として定義し、ハードコードを避ける
- **Relationの貼り方**: 既存ノードの検索 → なければ作成 → IDを使ってRelation設定の順
- **書き込み前に dry-run**: 本番DBへの書き込み前に `--dry-run` フラグで対象件数を確認できるようにする

## UPSERTのパターン

```python
# 重複排除キー（外部キー）で既存ノードを検索
external_key = sha256(f"{source_uri}|{source_timestamp}".encode()).hexdigest()
existing = notion_client.databases.query(
    database_id=settings.notion_db_knowledge_entry,
    filter={"property": "外部キー", "rich_text": {"equals": external_key}}
)

if existing["results"]:
    # 更新
    notion_client.pages.update(page_id=existing["results"][0]["id"], properties=...)
else:
    # 新規作成
    notion_client.pages.create(parent={...}, properties=...)
```

## レート制限への対応

- Notion APIは平均3リクエスト/秒の制限
- `tenacity` で指数バックオフ（初期1秒、最大32秒、リトライ5回）
- 大量書き込みは100件単位でチャンク化し、間に sleep を挟む

## よくある落とし穴

- **Rich Text の2,000文字制限**: 1プロパティあたり最大2,000文字。超える場合は分割するか、ページ本文（Block）として書き込む
- **Relation の同期方向**: Notionの双方向リレーションは自動同期される。片側を消すと相手側も消える
- **日付プロパティのタイムゾーン**: ISO 8601形式で `+09:00` を明示する
- **Select の選択肢自動追加**: 存在しない選択肢を指定すると自動追加される。誤字に注意
