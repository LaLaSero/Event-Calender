"""Utility module that sends outlet news summaries to an LLM and stores
normalized event data as JSON.

This implementation expects an OpenAI-compatible API key to be exposed via
the ``OPENAI_API_KEY`` environment variable. A default model can be supplied
through ``OPENAI_MODEL``; otherwise ``gpt-4o-mini`` is used.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List


try:
    from openai import OpenAI  # type: ignore
except ImportError:  # pragma: no cover - handled at runtime
    OpenAI = None  # type: ignore


class LLMParserError(RuntimeError):
    """Raised when the LLM parsing workflow cannot produce usable data."""


@dataclass
class ParsedEvent:
    name: str
    start_date: str
    end_date: str

    def as_dict(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }


SYSTEM_PROMPT = (
    "あなたは日本語のイベント情報から年に数回レベルの大型セールイベントを抽出するアシスタントです。もし大型セールが見つからなかったら，それに近しいイベントを一件だけ抽出してください．"
    "入力として与えられるテキストを読み取り、イベント名と開催期間から"
    "ISO8601形式 (YYYY-MM-DD) の開始日と終了日を抽出してください。"
    "終了日はイベント最終日とし、日付が1日しか分からない場合は"
    "start_date と end_date を同じ日にしてください。"
    "日付に年が含まれない場合は文脈から最も自然な年を推測し、"
    "推測が難しい場合は現在の年を用いてください。"
    "nameの欄にはアウトレット施設名を必ず最初に含めてください。"
    "必ず以下の JSON スキーマに従って返答してください:\n"
    "{\"events\": [{\"name\": string, \"start_date\": string, \"end_date\": string}]}"
)


def _load_client() -> "OpenAI":  # type: ignore[name-defined]
    if OpenAI is None:
        raise LLMParserError(
            "openai パッケージがインストールされていないため LLM を呼び出せません。"
        )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMParserError(
            "環境変数 'OPENAI_API_KEY' が設定されていません。"
        )

    return OpenAI(api_key=api_key)


def _normalise_events(payload: Dict[str, object]) -> List[ParsedEvent]:
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        raise LLMParserError("LLM 応答に有効な 'events' データが含まれていません。")

    normalised: List[ParsedEvent] = []
    for raw in events:
        if not isinstance(raw, dict):
            continue

        name = str(raw.get("name", "")).strip()
        start_date = str(raw.get("start_date", "")).strip()
        end_date = str(raw.get("end_date", "")).strip()

        if not name or not start_date or not end_date:
            continue

        normalised.append(ParsedEvent(name=name, start_date=start_date, end_date=end_date))

    if not normalised:
        raise LLMParserError("LLM 応答から有効なイベントを抽出できませんでした。")

    return normalised


def parse_events_with_llm(event_text: str, *, model: str | None = None, temperature: float = 0.0) -> List[ParsedEvent]:
    """Send the raw event bulletin text to the LLM and return parsed events."""

    if not event_text.strip():
        raise LLMParserError("解析対象のテキストが空です。")

    client = _load_client()
    model_name = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    try:
        response = client.chat.completions.create(  # type: ignore[attr-defined]
            model=model_name,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "以下のテキストからイベント情報を抽出してください。\n\n" + event_text
                    ),
                },
            ],
        )
    except Exception as exc:  # pragma: no cover - depends on remote API
        raise LLMParserError(f"LLM API 呼び出しに失敗しました: {exc}") from exc

    try:
        content = response.choices[0].message.content  # type: ignore[index]
    except Exception as exc:  # pragma: no cover - defensive
        raise LLMParserError("LLM からの応答を取得できませんでした。") from exc

    if not content:
        raise LLMParserError("LLM が空の応答を返しました。")

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMParserError("LLM の応答が JSON として解析できませんでした。") from exc

    return _normalise_events(payload)


def export_events_to_json(event_text: str, output_path: str, *, model: str | None = None) -> List[Dict[str, str]]:
    """Parse events via LLM and persist them to ``output_path``.

    Returns the list of dictionaries that were written.
    """

    parsed = parse_events_with_llm(event_text, model=model)
    events = [item.as_dict() for item in parsed]

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)

    return events

