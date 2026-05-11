"""Claude Haiku によるエンティティ名重複判定プロセッサ.

人/企業/プロジェクト/タグ などの名前リストから、表記揺れによる
重複エントリを検出する。実マージは別スクリプトで行う（本モジュールは判定のみ）。

設計方針:
- 過剰マージを避けるため、保守的に判定する（同姓同名は別扱い、曖昧な場合はマージしない）
- 入力リストのインデックスのみを返させ、Haiku に新規名称を発明させない
- バッチ単位で投入し、入力規模に応じて分割呼び出し
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


_VALID_ENTITY_KINDS = {"人", "企業・団体", "プロジェクト", "タグ"}


_SYSTEM_PROMPT_LENIENT_TPL = """\
あなたは社内ナレッジベースのエンティティ名重複判定アシスタントです。

入力された **{kind}** 名のリストから、**確実に同一エンティティを指す** もの同士をグループ化してください。

【判定基準（マージする）】
- 表記揺れ（例: 「BG」「BG社」「BG株式会社」、「山田太郎」「山田 太郎」「Yamada Taro」）
- 敬称・役職の有無（例: 「山田」「山田さん」「山田部長」「山田氏」）
- 全角/半角・大文字小文字の違い（例: 「ＡＢＣ」「ABC」「abc」）

【マージしない（保守的に判定）】
- 単に同じ語が含まれているだけ（例: 「山田太郎」≠「山田花子」、「BG資材」≠「BG営業」）
- 苗字または名のみで人物を特定できないもの（曖昧な場合は別扱い）
- 親会社と子会社（例: 「BG」≠「BGホールディングス」など組織階層が違うもの）
- 似ているが内容が異なるプロジェクト名

【出力フォーマット】
JSON のみ。マージするクラスタのみ列挙（残りは個別エンティティとして扱う）。

```json
{{
  "merges": [
    {{
      "canonical_index": 0,
      "merge_indices": [3, 7],
      "reason": "BG, BG社, BG株式会社 は同じ会社"
    }}
  ]
}}
```

- `canonical_index`: 入力リストのうち最も完全/正式と判断したエントリのインデックス（0-indexed）
- `merge_indices`: 同一視するその他のインデックス（canonical を含めない）
- `reason`: 簡潔な理由（30 文字程度）

マージ候補がなければ ``{{"merges": []}}`` を返してください。
"""


_SYSTEM_PROMPT_STRICT_TPL = """\
あなたは社内ナレッジベースの **{kind}** 名重複判定アシスタントです。

入力された名前リストから、**完全に同一の概念を指す表記揺れのみ** をグループ化してください。

【超厳格な判定原則】
1. 「関連している」「似ている」「同じテーマに属する」だけではマージ対象外
2. 接頭辞・接尾辞・修飾語が異なる場合は **別エンティティ** として扱う
3. 抽象概念とその具体例も別エンティティ（例: 「ISO」と「ISO 14064-2」は別）
4. 活動と結果も別エンティティ（例: 「MTG」と「MTG記録」は別）
5. 全体と一部も別エンティティ（例: 「Blue Balloon」と「Blue BalloonのHP更新」は別）
6. **少しでも疑わしい場合はマージしない**

【マージしてよい例（表記揺れのみ）】
- 大文字小文字の違い: 「core strategy」「Core Strategy」
- 全角/半角の違い: 「ＡＢＣ」「ABC」
- スペース・記号の有無: 「Gold Standard」「Goldstandard」、「C/N比」「CN比」
- 略称と完全形が **明白に同一** な場合: 「BG」「BG社」（「BG」が別組織を指さない場合）
- 前後の括弧記号: 「[400-bg-rd-method]」「400-bg-rd-method」

【絶対にマージしない例】
- 「LCA」「LCA手法」「LCA算出」「LCA評価」「LCA方法論」 — それぞれ別の概念
- 「GHG削減」「GHG算出」「GHG算定」 — 削減と算出は別工程
- 「BLOF」「BLOF実践」「BLOF生産者」 — 概念とその実装/対象者は別
- 「PDD」「PDD申請」 — 文書と申請プロセスは別
- 「DCM」「DCMホールディングス株式会社」 — 子会社と親会社は別の可能性
- 「ALBION」「ALBION白神研究所」 — 企業全体と一部門は別エンティティ

【自己反証チェック】
マージを提案する前に「これらは『関連する』だけでなく『完全に同じ』か？」を自問してください。
理由欄に「関連」「同じテーマ」「異なる文脈」と書きそうになったら **マージしないでください** 。

【出力フォーマット】
JSON のみ。マージしないなら空配列。

```json
{{
  "merges": [
    {{
      "canonical_index": 0,
      "merge_indices": [3, 7],
      "reason": "大文字小文字の違いのみ"
    }}
  ]
}}
```

- `canonical_index`: 入力リストのインデックス（0-indexed）
- `merge_indices`: 同一視するその他のインデックス
- `reason`: 「表記揺れ」のみマージ理由として有効。少しでも意味の違いがあれば空配列を返す
"""


# 後方互換のため（外部から参照されている可能性に備えて）
_SYSTEM_PROMPT_TPL = _SYSTEM_PROMPT_LENIENT_TPL


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
        logger.warning("dedup_json_parse_failed", raw_text_head=text[:200])
    return {}


class MergeProposal(BaseModel):
    """LLM から返される 1 つのマージ提案."""

    canonical_index: int
    merge_indices: list[int] = Field(default_factory=list)
    reason: str = ""


class DedupResult(BaseModel):
    """1 バッチの重複判定結果."""

    merges: list[MergeProposal] = Field(default_factory=list)


class EntityDeduplicator:
    """Claude Haiku でマスタDB エントリの重複候補を検出するプロセッサ."""

    def __init__(
        self,
        client: Anthropic,
        model: str,
        max_output_tokens: int = 1500,
        enable_prompt_caching: bool = True,
    ) -> None:
        self.client = client
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.enable_prompt_caching = enable_prompt_caching

    def detect_merges(
        self,
        entity_kind: str,
        names: list[str],
        strict: bool = False,
    ) -> DedupResult:
        """``names`` の中から重複候補を検出する.

        Args:
            entity_kind: 「人」「企業・団体」「プロジェクト」「タグ」のいずれか
            names: 候補名のリスト（順序が canonical/merge_indices の参照に使われる）
            strict: True の場合、より保守的な判定基準で過剰マージを抑制する
                （プロジェクト/タグなど意味的近接で別エンティティが多い種別で推奨）
        """
        if entity_kind not in _VALID_ENTITY_KINDS:
            raise ValueError(f"unknown entity_kind: {entity_kind!r}")
        if len(names) < 2:
            return DedupResult()

        tpl = _SYSTEM_PROMPT_STRICT_TPL if strict else _SYSTEM_PROMPT_LENIENT_TPL
        system_text = tpl.format(kind=entity_kind)
        system_dict: dict[str, Any] = {"type": "text", "text": system_text}
        if self.enable_prompt_caching:
            system_dict["cache_control"] = {"type": "ephemeral"}
        system_block = cast(TextBlockParam, system_dict)

        # 入力リストをインデックス付きでフォーマット
        listing = "\n".join(f"[{i}] {name}" for i, name in enumerate(names))
        user_content = f"入力リスト:\n{listing}"

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

        merges: list[MergeProposal] = []
        for m in payload.get("merges") or []:
            if not isinstance(m, dict):
                continue
            ci = m.get("canonical_index")
            mis = m.get("merge_indices") or []
            if not isinstance(ci, int):
                continue
            if not isinstance(mis, list):
                continue
            valid_mis = [int(i) for i in mis if isinstance(i, int) and 0 <= i < len(names)]
            if 0 <= ci < len(names) and valid_mis:
                merges.append(
                    MergeProposal(
                        canonical_index=ci,
                        merge_indices=[i for i in valid_mis if i != ci],
                        reason=str(m.get("reason", ""))[:200],
                    )
                )

        usage = response.usage
        logger.info(
            "dedup_batch_complete",
            model=self.model,
            entity_kind=entity_kind,
            n_input=len(names),
            n_merges=len(merges),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0),
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0),
        )
        return DedupResult(merges=merges)
