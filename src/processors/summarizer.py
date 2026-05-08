"""Claude API による要約・主述補完プロセッサ.

Phase 1 では「ミーティングメモから 3〜5 行の要約を生成する」最小機能を提供する。
タグ候補生成・エンティティ抽出は別モジュール（tagger.py / entity_extractor.py）に分割。

使用モデル: Sonnet 4.x（settings.anthropic_model_sonnet）
コスト目安: 1 件あたり数千トークン × Sonnet 4.x の単価 ≒ $0.01 前後
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from anthropic.types import TextBlockParam

from src.common.logger import get_logger

if TYPE_CHECKING:
    from anthropic import Anthropic

logger = get_logger(__name__)


# プロンプトキャッシング対象とするシステムプロンプト（90% 割引で再利用される）
_SYSTEM_PROMPT_SUMMARIZE = """\
あなたは BG社のミーティング議事録要約担当です。

入力されたメモを、以下の方針で 3〜5 行の日本語に要約してください。

【遵守事項】
- 主観的な発言は誰の発言かを明記する
- 数値・固有名詞は原文のまま保持する
- 専門用語は変えない
- 確信度の低い情報は「〜という意見もあった」のように婉曲化する
- 推測で情報を補わない（書かれていないことは書かない）
- 出力は要約本文のみ（前置き・見出し不要）"""


class Summarizer:
    """Claude API でテキストを要約するプロセッサ."""

    def __init__(
        self,
        client: Anthropic,
        model: str,
        max_output_tokens: int = 2000,
        enable_prompt_caching: bool = True,
    ) -> None:
        """Args:
        client: Anthropic クライアント
        model: 使用するモデル ID（例: ``claude-sonnet-4-6``）
        max_output_tokens: 1 件あたりの出力トークン上限
        enable_prompt_caching: システムプロンプトのキャッシングを有効化するか
        """
        self.client = client
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.enable_prompt_caching = enable_prompt_caching

    def summarize(self, title: str, body: str) -> str:
        """与えられた本文から要約文字列を生成する.

        Args:
            title: ソースのタイトル（コンテキストとしてプロンプトに含める）
            body: 要約対象の本文

        Returns:
            3〜5 行程度の日本語要約
        """
        system_dict: dict[str, Any] = {
            "type": "text",
            "text": _SYSTEM_PROMPT_SUMMARIZE,
        }
        if self.enable_prompt_caching:
            system_dict["cache_control"] = {"type": "ephemeral"}
        system_block = cast(TextBlockParam, system_dict)

        user_content = f"タイトル: {title}\n\n本文:\n{body}"

        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_output_tokens,
            system=[system_block],
            messages=[{"role": "user", "content": user_content}],
        )

        text_parts: list[str] = []
        for block in response.content:
            if getattr(block, "type", "") == "text":
                text_parts.append(getattr(block, "text", ""))
        summary = "".join(text_parts).strip()

        usage = response.usage
        logger.info(
            "summarize_complete",
            model=self.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0),
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0),
            summary_chars=len(summary),
        )
        return summary
