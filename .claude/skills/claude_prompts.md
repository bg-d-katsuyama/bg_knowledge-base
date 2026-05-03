# スキル: Claude API プロンプト設計

`src/processors/` 配下でClaude APIを呼ぶ際の指針。

## モデル使い分け

| 用途 | モデル | 理由 |
|---|---|---|
| 議事録要約・主述補完 | Sonnet 4.5 | 品質優先、日本語の文脈把握が必要 |
| エンティティ抽出（人・企業） | Haiku 4.5 | 定型処理、コスト優先 |
| タグ候補生成 | Haiku 4.5 | 分類タスク、軽量で十分 |
| Slackメッセージ分類 | Haiku 4.5 | 大量・軽量処理 |

`settings.anthropic_model_sonnet` / `settings.anthropic_model_haiku` を経由して指定する。直接モデル名をハードコードしないこと。

## プロンプトキャッシング

システムプロンプトと「BGの基本方針ドキュメント」は90%割引のキャッシュ対象。1024トークン以上で有効化。

```python
client.messages.create(
    model=settings.anthropic_model_sonnet,
    max_tokens=settings.claude_max_output_tokens,
    system=[
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": BG_GUIDELINES,
            "cache_control": {"type": "ephemeral"},
        },
    ],
    messages=[{"role": "user", "content": user_text}],
)
```

## Batch API

リアルタイム性が不要な日次バッチは50%割引のBatch APIを使う。

```python
# settings.claude_batch_api_enabled が True のときのみ使用
batch = client.messages.batches.create(requests=[...])
```

## プロンプト原則

1. **役割を最初に明示**: 「あなたはBG社のナレッジ整理担当です」のような明確な役割設定
2. **入出力フォーマットを構造化**: XML タグで区切る（`<input>`, `<output>`）
3. **JSON出力は専用構造**: 構造化抽出は Pydantic モデル + `tool_use` で行う
4. **チェーン・オブ・ソートを許容**: 複雑な判断は `<thinking>` タグで思考を促す
5. **ニュアンス保持**: 「原文の主観・確信度を維持してください」と明示

## ニュアンスの保持

打ち合わせで久保田様が懸念された「専門家の発言の確信度・角度が消える」問題への対策：

```
要約・主述補完を行う際、以下を必ず維持してください：
- 発言者がどの程度の確信を持って述べていたか（断定／推定／伝聞）
- 「〜らしい」「〜のはず」「〜と聞いた」等の助動詞・終助詞のニュアンス
- 数値の精度表現（「約3トン」と「ちょうど3トン」を区別）
- 専門家の所属と専門領域
```

## エラー時のフォールバック

- 出力がJSON parseできない → 1回だけプロンプトを修正してリトライ
- それでも失敗 → そのエントリは「未処理」ステータスのまま保存し、Cloud Loggingにエラー記録
- 連続失敗が10件超えたら全体停止

## コストロギング

すべてのClaude API呼び出しで以下を構造化ログに残す：

```python
logger.info(
    "claude_api_call",
    model=model_name,
    input_tokens=response.usage.input_tokens,
    output_tokens=response.usage.output_tokens,
    cache_read_tokens=response.usage.cache_read_input_tokens,
    pipeline=pipeline_name,
)
```
