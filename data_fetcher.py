import json
from typing import List

import requests

from fetchers import FetchError, BaseFetcher, get_fetcher


DEFAULT_FETCHER_NAME = "premium_outlets"


def _load_targets(targets_path: str) -> List[dict]:
    try:
        with open(targets_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"エラー: 設定ファイル '{targets_path}' が見つかりません。")
        return []


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            )
        }
    )
    return session


def fetch_events_from_api(targets_path: str) -> str:
    """設定ファイルをもとに各ターゲットの fetcher を選定し、イベント情報を収集する。"""

    print("--- APIからイベント情報取得開始 ---")
    targets = _load_targets(targets_path)

    if not targets:
        print("--- 情報取得完了 ---\n")
        return ""

    session = _build_session()
    all_events_text: List[str] = []

    for target in targets:
        fetcher_name = target.get("fetcher", DEFAULT_FETCHER_NAME)
        fetcher_cls = get_fetcher(fetcher_name)

        if fetcher_cls is None:
            name = target.get("name", fetcher_name)
            error_msg = (
                f"エラー: [{name}] に対応するフェッチャー '{fetcher_name}' が登録されていません。"
            )
            print(error_msg)
            all_events_text.append(f"--- {name}の情報 ---\n{error_msg}\n")
            continue

        fetcher: BaseFetcher = fetcher_cls(target, session)
        target_name = target.get("name", fetcher_name)

        api_url = target.get("api_url")
        if not api_url and fetcher_name == "premium_outlets":
            center_id = target.get("id")
            if center_id:
                api_url = f"https://www.premiumoutlets.co.jp/api/v1/{center_id}/news"

        if api_url:
            print(f"[{target_name}] の情報を取得中: {api_url}")
        else:
            print(f"[{target_name}] の情報を取得中: fetcher={fetcher_name}")

        try:
            outlet_text = fetcher.fetch()
        except FetchError as exc:
            error_msg = str(exc)
            print(error_msg)
            all_events_text.append(f"--- {target_name}の情報 ---\n{error_msg}\n")
            continue

        all_events_text.append(outlet_text)

    print("--- 情報取得完了 ---\n")
    return "\n".join(all_events_text)
