"""タグ候補生成プロセッサ.

使用モデル: Haiku 4.5（軽量タスク）。本文の内容を表す短いタグ語を 0〜5 個提案する。
カテゴリ（技術/戦略/運用/顧客/その他）も併せて返す。

戦略上の方針:
- 既存タグマスタとの照合は本プロセッサでは行わない（マスタ登録は loader 層で）
- 同義語の正規化は行わない（マスタ側の人手運用に委ねる）

コスト目安: 入力 ~2000 トークン × Haiku 4.5 ≒ $0.003/件
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, Literal, cast

from anthropic.types import TextBlockParam
from pydantic import BaseModel, Field

from src.common.logger import get_logger

if TYPE_CHECKING:
    from anthropic import Anthropic

logger = get_logger(__name__)


_VALID_CATEGORIES = {"技術", "戦略", "運用", "顧客", "その他"}


_SYSTEM_PROMPT_TAG = """\
あなたは BG 社のミーティングメモに対して、検索性向上のための「内容タグ」を提案する専任アシスタントです。

入力されたメモ（タイトル＋本文）から、内容を端的に表すタグを 0〜5 個 提案してください。

【タグの方針】
- 1タグは 1〜10 文字程度の短い名詞または名詞句
- BG 社の業務ドメイン語を優先（例: 「土壌」「堆肥」「LCA」「クレジット」「資材調達」「施肥設計」「方法論」「契約」「会計」「人事」「ガバナンス」「営業」「ブランディング」「広報」「研究」「監査」）
- 同じ意味のタグを 2 つ以上付けない
- タイトルや本文に明確な手掛かりがない場合は空配列でも構わない
- 推測で付けない

【カテゴリ】
各タグに対して、以下のいずれかのカテゴリを付与してください:
- 技術: 土壌科学・堆肥製造・LCA手法・栽培技術 等
- 戦略: 事業戦略・パートナーシップ・資金調達・方針決定 等
- 運用: 業務プロセス・スケジュール調整・進捗管理 等
- 顧客: 顧客企業・取引先・ステークホルダー対応 等
- その他: 上記いずれにも当てはまらない場合

【出力フォーマット】
出力は JSON のみ。説明文は付けない。

```json
{
  "tags": [
    {"name": "...", "category": "..."},
    {"name": "...", "category": "..."}
  ]
}
```"""


class TagSuggestion(BaseModel):
    """1 タグの提案."""

    name: str
    category: Literal["技術", "戦略", "運用", "顧客", "その他"] = "その他"


class GeneratedTags(BaseModel):
    """生成されたタグ群."""

    tags: list[TagSuggestion] = Field(default_factory=list)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _parse_json_payload(text: str) -> dict[str, Any]:
    text = text.strip()
    m = _JSON_FENCE_RE.search(text)
    payload = m.group(1) if m else text
    try:
        result = json.loads(payload)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        logger.warning("tag_json_parse_failed", raw_text_head=text[:200])
    return {}


def _coerce_tags(raw: Any) -> list[TagSuggestion]:
    if not isinstance(raw, list):
        return []
    seen_names: set[str] = set()
    out: list[TagSuggestion] = []
    for v in raw:
        if not isinstance(v, dict):
            continue
        name_val = v.get("name")
        cat_val = v.get("category")
        if not isinstance(name_val, str):
            continue
        name = name_val.strip()
        if not name or name in seen_names:
            continue
        category = cat_val if isinstance(cat_val, str) and cat_val in _VALID_CATEGORIES else "その他"
        seen_names.add(name)
        out.append(TagSuggestion(name=name, category=cast(Any, category)))
    return out


class Tagger:
    """Claude Haiku でタグ候補を生成するプロセッサ."""

    def __init__(
        self,
        client: Anthropic,
        model: str,
        max_output_tokens: int = 500,
        enable_prompt_caching: bool = True,
    ) -> None:
        self.client = client
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.enable_prompt_caching = enable_prompt_caching

    def generate(self, title: str, body: str) -> GeneratedTags:
        system_dict: dict[str, Any] = {
            "type": "text",
            "text": _SYSTEM_PROMPT_TAG,
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
        tags = _coerce_tags(payload.get("tags"))
        result = GeneratedTags(tags=tags)

        usage = response.usage
        logger.info(
            "tag_generate_complete",
            model=self.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0),
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0),
            n_tags=len(result.tags),
        )
        return result
