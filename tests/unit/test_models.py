"""src/common/models.py の単体テスト."""

from __future__ import annotations

from datetime import UTC, datetime


def test_knowledge_entry_external_key_is_deterministic() -> None:
    """同じ source_url・occurred_at から同じ外部キーが生成されること."""
    from src.common.models import KnowledgeEntry, ProcessingStatus, SourceType

    occurred_at = datetime(2026, 4, 24, 10, 0, 0, tzinfo=UTC)
    e1 = KnowledgeEntry(
        title="テスト",
        occurred_at=occurred_at,
        source_type=SourceType.MANUAL,
        source_url="https://example.com/doc1",
        creator_name="勝山",
        summary="要約",
        body_revised="本文",
        body_original="原文",
        status=ProcessingStatus.PENDING,
    )
    e2 = KnowledgeEntry(
        title="別のタイトル",
        occurred_at=occurred_at,
        source_type=SourceType.MEET,
        source_url="https://example.com/doc1",
        creator_name="久保田",
        summary="別要約",
        body_revised="別本文",
        body_original="別原文",
        status=ProcessingStatus.AI_PROCESSED,
    )
    # 外部キーは source_url と occurred_at にのみ依存する
    assert e1.external_key == e2.external_key
    assert len(e1.external_key) == 64  # SHA256


def test_knowledge_entry_external_key_changes_with_url() -> None:
    """source_url が異なれば外部キーが変わること."""
    from src.common.models import KnowledgeEntry, ProcessingStatus, SourceType

    occurred_at = datetime(2026, 4, 24, 10, 0, 0, tzinfo=UTC)
    common_kwargs = {
        "title": "テスト",
        "occurred_at": occurred_at,
        "source_type": SourceType.MANUAL,
        "creator_name": "勝山",
        "summary": "要約",
        "body_revised": "本文",
        "body_original": "原文",
        "status": ProcessingStatus.PENDING,
    }
    e1 = KnowledgeEntry(source_url="https://example.com/a", **common_kwargs)
    e2 = KnowledgeEntry(source_url="https://example.com/b", **common_kwargs)
    assert e1.external_key != e2.external_key
