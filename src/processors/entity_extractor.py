"""人・企業・プロジェクトエンティティ抽出プロセッサ.

使用モデル: Haiku 4.5（軽量タスク）。本文から固有名詞（人名・企業/団体名・
プロジェクト/テーマ名）を抽出し、JSON で返す。

戦略上の方針:
- 同名別人問題は初期は同一視（人手で後分離する運用）。
- 推測は禁止。本文に明記された名前のみを返す。
- 創設者（メモ作成者）は creator として別フィールドで返す（特定できなければ null）。

コスト目安: 入力 ~2000 トークン × Haiku 4.5 ≒ $0.003/件
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, cast

from anthropic.types import TextBlockParam
from pydantic import BaseModel, Field

from src.common.logger import get_logger

if TYPE_CHECKING:
    from anthropic import Anthropic

logger = get_logger(__name__)


_SYSTEM_PROMPT_ENTITY = """\
あなたは BG 社のミーティングメモから固有名詞を抽出する専任アシスタントです。

入力されたメモ（タイトル＋本文）から、以下の3カテゴリの固有名詞を抽出してください。

【抽出対象】
1. people: 人名（個人）。例: 「久保田」「山田太郎」「ジョン・スミス」
   - 敬称（さん・様・氏・先生・社長 等）は **除いた名前のみ** を返す
   - 役職のみ（「社長」「弁護士」等）は人名として扱わない
2. organizations: 企業・団体・部署名。例: 「BG」「ABC社」「経産省」「鈴鹿農園」
   - 「BG社」「BG株式会社」などの表記揺れは原文の最も完全な形で返す
3. projects: プロジェクト・テーマ名。例: 「資材調達プロジェクト」「LCA算定」「Agri LCA+」
   - 単なる「定例」「打ち合わせ」のような一般語は除く

【遵守事項】
- 本文に **明記されていない** 名前は返さない（推測禁止）
- 重複する名前は1回だけ返す
- 各カテゴリは空配列でも構わない
- 出力は JSON のみ。説明文は付けない。

【出力フォーマット】
```json
{
  "people": ["...", "..."],
  "organizations": ["...", "..."],
  "projects": ["...", "..."]
}
```"""


class ExtractedEntities(BaseModel):
    """抽出されたエンティティ群."""

    people: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _parse_json_payload(text: str) -> dict[str, Any]:
    """LLM 出力から JSON 辞書を抽出する.

    出力が ``` で囲まれていても、素のJSONでも対応する。
    パース失敗時は空辞書を返す（落ちさせず継続させる）。
    """
    text = text.strip()
    m = _JSON_FENCE_RE.search(text)
    payload = m.group(1) if m else text
    try:
        result = json.loads(payload)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        logger.warning("entity_json_parse_failed", raw_text_head=text[:200])
    return {}


def _normalize_str_list(raw: Any) -> list[str]:
    """LLM 返却値を文字列リストに正規化（重複除去・空白除外・先頭末尾trim）."""
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for v in raw:
        if not isinstance(v, str):
            continue
        s = v.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


class EntityExtractor:
    """Claude Haiku で人・企業・プロジェクトを抽出するプロセッサ."""

    def __init__(
        self,
        client: Anthropic,
        model: str,
        max_output_tokens: int = 1000,
        enable_prompt_caching: bool = True,
    ) -> None:
        """Args:
        client: Anthropic クライアント
        model: 使用するモデル ID（例: ``claude-haiku-4-5``）
        max_output_tokens: 1 件あたりの出力トークン上限
        enable_prompt_caching: システムプロンプトのキャッシングを有効化するか
        """
        self.client = client
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.enable_prompt_caching = enable_prompt_caching

    def extract(self, title: str, body: str) -> ExtractedEntities:
        """与えられたメモから人・企業・プロジェクトを抽出する."""
        system_dict: dict[str, Any] = {
            "type": "text",
            "text": _SYSTEM_PROMPT_ENTITY,
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
        raw = "".join(text_parts).strip()

        payload = _parse_json_payload(raw)
        result = ExtractedEntities(
            people=_normalize_str_list(payload.get("people")),
            organizations=_normalize_str_list(payload.get("organizations")),
            projects=_normalize_str_list(payload.get("projects")),
        )

        usage = response.usage
        logger.info(
            "entity_extract_complete",
            model=self.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0),
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0),
            n_people=len(result.people),
            n_orgs=len(result.organizations),
            n_projects=len(result.projects),
        )
        return result
