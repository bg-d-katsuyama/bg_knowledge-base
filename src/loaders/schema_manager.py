"""Notion スキーマ定義（プロパティ名の定数化）.

ハードコードを避け、各DBのプロパティ名を一元管理する。
スキーマ変更時は `docs/schema.md` と本ファイルを同時に更新すること。
"""

from __future__ import annotations


class KnowledgeEntryProps:
    """ナレッジエントリDBのプロパティ名."""

    TITLE = "タイトル"
    OCCURRED_AT = "日時"
    SOURCE_TYPE = "ソース種別"
    SOURCE_URL = "ソースURL"
    CREATOR = "作成者"
    RELATED_PEOPLE = "関係者（人）"
    RELATED_ORGS = "関係先（組織）"
    RELATED_PROJECTS = "関連プロジェクト"
    RELATED_FILES = "関連フォルダ/ファイル"
    TAGS = "内容タグ"
    SUMMARY = "要約"
    BODY_REVISED = "本文（補完済み）"
    BODY_ORIGINAL = "本文（原文）"
    RATIONALE = "背景・理由"
    STATUS = "処理ステータス"
    CONFIDENCE = "信頼度"
    EXTERNAL_KEY = "外部キー"


class PersonProps:
    """人DBのプロパティ名."""

    NAME = "氏名"
    NAME_KANA = "よみがな"
    ORGANIZATION = "所属"
    EXPERTISE = "専門領域"
    INTERNAL_FLAG = "BG内/外"
    EMAIL = "連絡先"
    NOTES = "備考"


class OrganizationProps:
    """企業・団体DBのプロパティ名."""

    NAME = "名称"
    INDUSTRY = "業界"
    BG_RELATION = "BGとの関係"
    CONTACT = "連絡窓口"


class ProjectProps:
    """プロジェクト/テーマDBのプロパティ名."""

    NAME = "プロジェクト名"
    STATUS = "ステータス"
    OWNER = "主担当"
    PARENT = "親テーマ"


class TagProps:
    """タグDBのプロパティ名."""

    NAME = "タグ名"
    CATEGORY = "カテゴリ"
    PARENT = "親タグ"
    DESCRIPTION = "説明"
