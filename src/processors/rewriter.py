"""本文リライト（主述補完）プロセッサ.

使用モデル: Sonnet 4.x。メモの省略形（主語・目的語の省略、口語表現、断片的な箇条書き）を
補完して、初見の読み手でも理解できる文章に変換する。原文は別途保持する
（KnowledgeEntry.body_original）。

戦略上の方針:
- 推測で内容を増やさない（主述補完のみ・新規情報の追加禁止）
- 文章構成・段落分けは原文の構造を尊重
- 専門用語・固有名詞・数値は原文のまま保持
- 長すぎる本文（>10000 文字）は処理コスト面でリライトをスキップし、原文を返す

コスト目安: 入力 ~2000 + 出力 ~3000 トークン × Sonnet 4.x ≒ $0.05/件
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from anthropic.types import TextBlockParam

from src.common.logger import get_logger

if TYPE_CHECKING:
    from anthropic import Anthropic

logger = get_logger(__name__)


_REVISE_BODY_MAX_CHARS = 10000


_SYSTEM_PROMPT_REVISE = """\
あなたは BG 社のミーティングメモを、初見の読み手にも理解できる文章に整えるアシスタントです。

入力されたメモ（タイトル＋本文）に対して、以下の方針でリライトしてください。

【リライト方針】
- 省略された主語・目的語を補完する（誰が・誰に・何を、を明示）
- 口語的・断片的な表現を簡潔な書き言葉に整える
- 箇条書きや段落構造は原文を尊重し、無闇に統合しない
- 専門用語・固有名詞・数値・日付は原文のまま保持する
- 「〜らしい」「〜のはず」など曖昧表現は原文の通り残す（断定に変えない）

【厳守事項】
- 本文に書かれていない情報を追加しない（推測・補強・コメント禁止）
- 要約は別タスクなので、内容は省略しない（むしろ補って明確化する）
- 出力はリライト後の本文のみ。前置き・要約・解説・「以下にリライト後の本文を示します」のような枕詞は不要

【入出力フォーマット】
入力: タイトルと本文
出力: リライト後の本文のみ（マークダウン構造は原文に合わせる）"""


class BodyReviser:
    """Claude Sonnet で本文を主述補完するプロセッサ."""

    def __init__(
        self,
        client: Anthropic,
        model: str,
        max_output_tokens: int = 4000,
        enable_prompt_caching: bool = True,
    ) -> None:
        """Args:
        client: Anthropic クライアント
        model: 使用するモデル ID（例: ``claude-sonnet-4-5``）
        max_output_tokens: 1 件あたりの出力トークン上限
        enable_prompt_caching: システムプロンプトのキャッシングを有効化するか
        """
        self.client = client
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.enable_prompt_caching = enable_prompt_caching

    def revise(self, title: str, body: str) -> str:
        """与えられた本文を主述補完して返す.

        - 本文が空または非常に短い場合は原文をそのまま返す
        - 本文が長すぎる（>10000文字）場合もコスト保護のため原文を返す
        """
        body = body or ""
        if len(body.strip()) < 30:
            return body
        if len(body) > _REVISE_BODY_MAX_CHARS:
            logger.info(
                "rewrite_skipped_long_body",
                body_chars=len(body),
                threshold=_REVISE_BODY_MAX_CHARS,
            )
            return body

        system_dict: dict[str, Any] = {
            "type": "text",
            "text": _SYSTEM_PROMPT_REVISE,
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
        revised = "".join(text_parts).strip()

        usage = response.usage
        logger.info(
            "rewrite_complete",
            model=self.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0),
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0),
            original_chars=len(body),
            revised_chars=len(revised),
        )
        # LLM が空文字を返した場合は原文を返す（フォールバック）
        return revised or body
