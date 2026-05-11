"""Slack メッセージリーダー（バッチ取り込み用）.

指定された channel のすべてのトップレベルメッセージとスレッド返信を
イテレータとして取り出し、共通の `SlackMessage` データクラスに正規化する。
ユーザー ID → 表示名解決、メンション展開、リアクション・添付ファイルの集約まで行う。

設計上の不変条件:
- 本リーダーは Slack に対して **読み取り API のみ** を呼ぶ
- メッセージ書き込み・削除・更新は一切行わない
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from slack_sdk.errors import SlackApiError

from src.common.logger import get_logger

if TYPE_CHECKING:
    from slack_sdk import WebClient

logger = get_logger(__name__)


_MENTION_RE = re.compile(r"<@([A-Z0-9]+)>")
_CHANNEL_LINK_RE = re.compile(r"<#([A-Z0-9]+)\|([^>]*)>")
_USER_GROUP_RE = re.compile(r"<!subteam\^([A-Z0-9]+)\|([^>]*)>")
_GENERIC_LINK_RE = re.compile(r"<(https?://[^|>]+)\|([^>]+)>")
_BARE_LINK_RE = re.compile(r"<(https?://[^>]+)>")


@dataclass
class SlackMessage:
    """1 つの Slack メッセージ（親 or 返信）の正規化表現."""

    channel_id: str
    channel_name: str
    workspace_url: str
    """末尾スラッシュ付き、例: ``https://blactogreen.slack.com/``"""
    ts: str
    """メッセージのタイムスタンプ（Slack のメッセージID）"""
    thread_ts: str | None
    """スレッドの親メッセージ ts。スレッド外メッセージは ``None``。親自身は ``ts == thread_ts``"""
    parent_ts: str | None
    """このメッセージが返信なら親メッセージの ts、それ以外は ``None``"""
    user_id: str | None
    user_name: str | None
    """解決済みの表示名（解決失敗時は user_id をフォールバック）"""
    text_raw: str
    """Slack 元の text（``<@U123>`` 等の生データを含む）"""
    text_resolved: str
    """メンションやチャンネル参照を読みやすい形に展開したテキスト"""
    occurred_at: datetime
    """投稿時刻（UTC）。編集されている場合も投稿時刻を採用"""
    edited_at: datetime | None
    reactions: list[tuple[str, int]] = field(default_factory=list)
    """``[(emoji_name, count), ...]``"""
    files: list[dict[str, str]] = field(default_factory=list)
    """``[{"name": "...", "url": "...", "mimetype": "..."}]``"""
    is_thread_parent: bool = False
    """このメッセージがスレッド親（reply_count > 0）であれば True"""
    reply_count: int = 0
    subtype: str | None = None
    """``channel_join`` など、投稿以外のシステムメッセージは subtype が付く"""

    @property
    def permalink(self) -> str:
        """Slack permalink を組み立てる（API 呼び出しなし）.

        例: ``https://blactogreen.slack.com/archives/C0XXX/p1234567890123456``
        スレッド返信の場合 ``?thread_ts=...&cid=...`` を付与する。
        """
        ts_no_dot = self.ts.replace(".", "")
        base = f"{self.workspace_url}archives/{self.channel_id}/p{ts_no_dot}"
        if self.parent_ts:
            return f"{base}?thread_ts={self.parent_ts}&cid={self.channel_id}"
        return base


def _ts_to_datetime(ts: str) -> datetime:
    """Slack の ts (例 ``1234567890.123456``) を UTC datetime に変換."""
    return datetime.fromtimestamp(float(ts), tz=UTC)


def _retry_on_rate_limit(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Slack のレート制限 (HTTP 429) で Retry-After 秒待ってリトライする小ヘルパ."""
    while True:
        try:
            return fn(*args, **kwargs)
        except SlackApiError as e:
            if e.response.get("error") == "ratelimited":
                ra = int(e.response.headers.get("Retry-After", "5"))
                logger.warning("slack_rate_limited", retry_after=ra)
                time.sleep(ra)
                continue
            raise


class SlackReader:
    """Slack のチャンネル履歴を `SlackMessage` イテレータとして提供する Reader."""

    def __init__(self, client: WebClient) -> None:
        """Args: client: 認証済み Slack WebClient."""
        self.client = client
        self._user_cache: dict[str, str] = {}
        self._workspace_url: str | None = None

    # ---- 内部ヘルパ -------------------------------------------------

    def _get_workspace_url(self) -> str:
        if self._workspace_url:
            return self._workspace_url
        r = cast(dict[str, Any], _retry_on_rate_limit(self.client.auth_test))
        url = cast(str, r["url"])
        if not url.endswith("/"):
            url = url + "/"
        self._workspace_url = url
        return url

    def _resolve_user(self, user_id: str | None) -> str | None:
        if not user_id:
            return None
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        try:
            r = cast(
                dict[str, Any],
                _retry_on_rate_limit(self.client.users_info, user=user_id),
            )
            user = r.get("user") or {}
            profile = user.get("profile") or {}
            name = (
                profile.get("display_name_normalized")
                or profile.get("real_name_normalized")
                or profile.get("display_name")
                or profile.get("real_name")
                or user.get("name")
                or user_id
            )
            self._user_cache[user_id] = name
            return name
        except SlackApiError as e:
            logger.warning("slack_user_lookup_failed", user_id=user_id, error=str(e)[:120])
            self._user_cache[user_id] = user_id  # ネガティブキャッシュ
            return user_id

    def _resolve_text(self, text: str) -> str:
        """テキスト中の Slack 構文を読みやすい形に展開する."""
        if not text:
            return ""
        # mention <@U123>
        def _sub_mention(m: re.Match[str]) -> str:
            uid = m.group(1)
            name = self._resolve_user(uid)
            return f"@{name}" if name else m.group(0)

        text = _MENTION_RE.sub(_sub_mention, text)
        # channel link <#C123|name>
        text = _CHANNEL_LINK_RE.sub(lambda m: f"#{m.group(2) or m.group(1)}", text)
        # user group <!subteam^S123|name>
        text = _USER_GROUP_RE.sub(lambda m: f"@{m.group(2) or m.group(1)}", text)
        # generic link <https://x|label>
        text = _GENERIC_LINK_RE.sub(lambda m: f"{m.group(2)} ({m.group(1)})", text)
        # bare link <https://x>
        text = _BARE_LINK_RE.sub(lambda m: m.group(1), text)
        # Slack のエスケープ &amp; &lt; &gt; を戻す
        return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")

    def _normalize(
        self,
        msg: dict[str, Any],
        channel_id: str,
        channel_name: str,
        parent_ts: str | None,
    ) -> SlackMessage:
        ts = cast(str, msg["ts"])
        thread_ts = cast(str | None, msg.get("thread_ts"))
        edited = msg.get("edited") or {}
        edited_ts = edited.get("ts")
        reactions: list[tuple[str, int]] = []
        for r in msg.get("reactions") or []:
            name = r.get("name", "")
            count = int(r.get("count", 0))
            if name and count > 0:
                reactions.append((name, count))
        files: list[dict[str, str]] = []
        for f in msg.get("files") or []:
            files.append(
                {
                    "name": str(f.get("name", "")),
                    "url": str(f.get("url_private", "")),
                    "mimetype": str(f.get("mimetype", "")),
                }
            )
        user_id = cast(str | None, msg.get("user") or msg.get("bot_id"))
        user_name = self._resolve_user(user_id) if user_id else None
        text_raw = cast(str, msg.get("text") or "")
        text_resolved = self._resolve_text(text_raw)
        reply_count = int(msg.get("reply_count") or 0)
        is_thread_parent = (parent_ts is None) and (reply_count > 0 or thread_ts == ts)

        return SlackMessage(
            channel_id=channel_id,
            channel_name=channel_name,
            workspace_url=self._get_workspace_url(),
            ts=ts,
            thread_ts=thread_ts,
            parent_ts=parent_ts,
            user_id=user_id,
            user_name=user_name,
            text_raw=text_raw,
            text_resolved=text_resolved,
            occurred_at=_ts_to_datetime(ts),
            edited_at=_ts_to_datetime(edited_ts) if edited_ts else None,
            reactions=reactions,
            files=files,
            is_thread_parent=is_thread_parent,
            reply_count=reply_count,
            subtype=cast(str | None, msg.get("subtype")),
        )

    # ---- パブリック API ---------------------------------------------

    def get_channel_meta(self, channel_id: str) -> dict[str, Any]:
        r = cast(
            dict[str, Any],
            _retry_on_rate_limit(
                self.client.conversations_info,
                channel=channel_id,
                include_num_members=True,
            ),
        )
        return cast(dict[str, Any], r.get("channel") or {})

    def iter_messages(
        self,
        channel_id: str,
        sleep_between_pages: float = 0.3,
    ) -> Iterator[SlackMessage]:
        """指定チャンネルの全メッセージ（親 + 返信）をイテレータで返す.

        順序: 古いメッセージから順に yield する（occurred_at 昇順）。
        スレッド親の直後にそのスレッドの返信群を続けて yield する。

        Args:
            channel_id: 対象チャンネルの ID（``C0XXXX...``）
            sleep_between_pages: API 呼び出し間のスリープ秒（レート制限緩和）
        """
        meta = self.get_channel_meta(channel_id)
        channel_name = cast(str, meta.get("name") or channel_id)

        # Step 1: トップレベルメッセージを全件取得（新→旧で返るので末尾で逆順化）
        parents: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"channel": channel_id, "limit": 200}
            if cursor:
                kwargs["cursor"] = cursor
            r = cast(
                dict[str, Any],
                _retry_on_rate_limit(self.client.conversations_history, **kwargs),
            )
            parents.extend(r.get("messages", []))
            cursor = (r.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
            time.sleep(sleep_between_pages)

        # 古い順に
        parents.sort(key=lambda m: float(m["ts"]))

        for parent in parents:
            parent_msg = self._normalize(parent, channel_id, channel_name, parent_ts=None)
            yield parent_msg
            if parent_msg.is_thread_parent:
                # Step 2: 返信群を取得
                rcursor: str | None = None
                while True:
                    kwargs2: dict[str, Any] = {
                        "channel": channel_id,
                        "ts": parent_msg.ts,
                        "limit": 200,
                    }
                    if rcursor:
                        kwargs2["cursor"] = rcursor
                    rr = cast(
                        dict[str, Any],
                        _retry_on_rate_limit(self.client.conversations_replies, **kwargs2),
                    )
                    replies = rr.get("messages", []) or []
                    # 1件目は親自身が返ってくることがあるので除外
                    for rep in replies:
                        if rep.get("ts") == parent_msg.ts:
                            continue
                        yield self._normalize(
                            rep, channel_id, channel_name, parent_ts=parent_msg.ts
                        )
                    rcursor = (rr.get("response_metadata") or {}).get("next_cursor")
                    if not rcursor:
                        break
                    time.sleep(sleep_between_pages)
