"""Fetcher strategy implementations for various event sources."""

from __future__ import annotations

import abc
from pathlib import Path
from typing import Any, Dict, Optional, Type

import requests
from bs4 import BeautifulSoup


class FetchError(RuntimeError):
    """Raised when a specific fetcher fails to gather data."""


class BaseFetcher(abc.ABC):
    """Abstract base class for fetcher strategies."""

    def __init__(self, target: Dict[str, Any], session: requests.Session):
        self.target = target
        self.session = session

    @abc.abstractmethod
    def fetch(self) -> str:
        """Fetch event information and return formatted text."""


FETCHER_REGISTRY: Dict[str, Type[BaseFetcher]] = {}


def register_fetcher(name: str):
    """Class decorator used to register fetcher implementations."""

    def decorator(cls: Type[BaseFetcher]) -> Type[BaseFetcher]:
        FETCHER_REGISTRY[name] = cls
        return cls

    return decorator


def get_fetcher(name: str) -> Optional[Type[BaseFetcher]]:
    return FETCHER_REGISTRY.get(name)


@register_fetcher("premium_outlets")
class PremiumOutletsFetcher(BaseFetcher):
    """Fetcher for Premium Outlets news API."""

    CATEGORY01_NEWS = 10  # プレミアム・アウトレットニュースカテゴリ
    CATEGORY02_PREMIUM_OUTLETS_NEWS = 200

    def fetch(self) -> str:
        center_name = self.target.get("name", "不明なアウトレット")
        center_id = self.target.get("id")
        if not center_id:
            raise FetchError(f"ターゲット '{center_name}' に 'id' が設定されていません。")

        api_url = self.target.get(
            "api_url",
            f"https://www.premiumoutlets.co.jp/api/v1/{center_id}/news",
        )

        try:
            response = self.session.get(api_url, timeout=15)
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - network
            raise FetchError(
                f"エラー: [{center_name}] のAPIアクセスに失敗しました。: {exc}"
            ) from exc

        events_data = response.json()
        news_items = events_data.get("news", []) if isinstance(events_data, dict) else []

        outlet_text = f"--- {center_name}のイベント情報 ---\n"
        found_events = False

        for news in news_items:
            if not isinstance(news, dict):
                continue

            if news.get("category01") != self.CATEGORY01_NEWS:
                continue

            if news.get("category02") != self.CATEGORY02_PREMIUM_OUTLETS_NEWS:
                continue

            title = (news.get("title") or "").strip()
            period = (news.get("schedule") or news.get("period") or "").strip()

            if not title or not period:
                continue

            outlet_text += f"イベント名: {title}, 期間: {period}\n"
            found_events = True

        if not found_events:
            outlet_text += "現在、対象となるイベント情報はありません。\n"

        return outlet_text


@register_fetcher("placeholder_html")
class PlaceholderHTMLFetcher(BaseFetcher):
    """Prototype for HTML scraping fetchers.

    Currently acts as a stub to illustrate how alternative strategies can be
    registered without affecting existing functionality.
    """

    def fetch(self) -> str:
        name = self.target.get("name", "未設定ターゲット")
        url = self.target.get("url", "")
        raise FetchError(
            f"[{name}] 用の HTML フェッチャーは未実装です。対象URL: {url}"
        )


@register_fetcher("html_css")
class HTMLCSSFetcher(BaseFetcher):
    """Simple CSS selector driven HTML fetcher.

    The target configuration can include the following keys:

    - ``url``: HTTP(S) URL to fetch. Optional if ``local_file`` is supplied.
    - ``local_file``: Path to a local HTML file (useful for testing).
    - ``card_selector``: CSS selector for each event/product card.
    - ``title_selector``: CSS selector (relative to the card) to extract text.
    - ``period_selector``: Optional CSS selector for the period/date field.
    - ``static_period``: Fallback text used when no period can be extracted.
    - ``limit``: Optional integer to limit the number of cards processed.
    """

    def fetch(self) -> str:
        name = self.target.get("name", "HTMLターゲット")
        markup = self._load_markup()

        soup = BeautifulSoup(markup, "html.parser")

        card_selector = self.target.get("card_selector")
        if not card_selector:
            raise FetchError(
                f"[{name}] に card_selector が設定されていません。"
            )

        cards = soup.select(card_selector)
        limit = self.target.get("limit")
        if isinstance(limit, int) and limit > 0:
            cards = cards[:limit]

        title_selector = self.target.get("title_selector")
        period_selector = self.target.get("period_selector")
        static_period = self.target.get("static_period", "期間情報なし")

        outlet_text = f"--- {name}のイベント情報 ---\n"
        found = False

        for card in cards:
            title_text = None
            if title_selector:
                title_node = card.select_one(title_selector)
                if title_node:
                    title_text = title_node.get_text(strip=True)
            else:
                title_text = card.get_text(strip=True)

            if not title_text:
                continue

            period_text = static_period
            if period_selector:
                period_node = card.select_one(period_selector)
                if period_node:
                    text = period_node.get_text(strip=True)
                    if text:
                        period_text = text

            outlet_text += f"イベント名: {title_text}, 期間: {period_text}\n"
            found = True

        if not found:
            outlet_text += "現在、対象となるイベント情報はありません。\n"

        return outlet_text

    def _load_markup(self) -> str:
        local_file = self.target.get("local_file")
        if local_file:
            path = Path(local_file).expanduser()
            if not path.exists():
                raise FetchError(f"ローカルファイル '{path}' が見つかりません。")
            return path.read_text(encoding="utf-8")

        url = self.target.get("url")
        if not url:
            raise FetchError("URL もしくは local_file の指定が必要です。")

        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise FetchError(f"HTMLページの取得に失敗しました: {exc}") from exc

        return response.text
