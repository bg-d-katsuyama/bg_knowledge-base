"""共通データモデル.

ナレッジエントリ、人、企業、プロジェクト、タグの内部表現を定義する。
Notionプロパティとのマッピングは `src/loaders/notion_writer.py` で行う。
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class SourceType(StrEnum):
    """ソース種別."""

    MEET = "Meet議事録"
    MANUAL = "手動メモ"
    SLACK = "Slack"
    DRIVE = "Driveファイル"
    OTHER = "その他"


class ProcessingStatus(StrEnum):
    """処理ステータス."""

    PENDING = "未処理"
    AI_PROCESSED = "AI加工済"
    HUMAN_VERIFIED = "人検証済"


class ConfidenceLevel(StrEnum):
    """信頼度."""

    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"


class Person(BaseModel):
    """人マスタ."""

    model_config = ConfigDict(frozen=False, str_strip_whitespace=True)

    name: str
    name_kana: str | None = None
    organization_name: str | None = None
    expertise: list[str] = Field(default_factory=list)
    is_internal: bool = False
    email: str | None = None
    phone: str | None = None
    notes: str | None = None


class Organization(BaseModel):
    """企業・団体マスタ."""

    model_config = ConfigDict(frozen=False, str_strip_whitespace=True)

    name: str
    industry: str | None = None
    relations: list[str] = Field(default_factory=list)


class Project(BaseModel):
    """プロジェクト/テーマ."""

    model_config = ConfigDict(frozen=False, str_strip_whitespace=True)

    name: str
    status: Literal["計画中", "進行中", "完了", "保留"] = "進行中"
    parent_theme: str | None = None


class Tag(BaseModel):
    """内容タグ（階層構造可）."""

    model_config = ConfigDict(frozen=False, str_strip_whitespace=True)

    name: str
    category: Literal["技術", "戦略", "運用", "顧客", "その他"] = "その他"
    parent_tag: str | None = None
    description: str | None = None


class SourceDocument(BaseModel):
    """ソースから読み取った生のドキュメントを表す中間型.

    Reader 層が生成し、Processor / Loader 層に渡す。
    """

    model_config = ConfigDict(frozen=False, str_strip_whitespace=True)

    source_id: str
    """ソース側の一意識別子（Notion ページ ID 等）"""
    title: str
    source_url: str
    body: str
    """抽出されたプレーンテキスト本文"""
    last_edited_time: datetime
    source_type: SourceType


class KnowledgeEntry(BaseModel):
    """ナレッジエントリ（メインDB）の内部表現."""

    model_config = ConfigDict(frozen=False, str_strip_whitespace=True)

    title: str
    occurred_at: datetime
    source_type: SourceType
    source_url: HttpUrl | str
    creator_name: str | None = None
    related_people: list[str] = Field(default_factory=list)
    related_organizations: list[str] = Field(default_factory=list)
    related_projects: list[str] = Field(default_factory=list)
    related_files: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    summary: str
    body_revised: str
    body_original: str
    rationale: str | None = None
    status: ProcessingStatus = ProcessingStatus.PENDING
    confidence: ConfidenceLevel | None = None

    @property
    def external_key(self) -> str:
        """重複排除用の外部キー（SHA256）.

        `source_url + occurred_at` から生成する。
        """
        seed = f"{self.source_url}|{self.occurred_at.isoformat()}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()
