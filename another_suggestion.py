import json
from datetime import datetime, timedelta
import re
from typing import List, Dict, Any
from icalendar import Calendar, Event
import os
from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
import argparse

SALES_JSON_PATH = "sales.json"

# 初回のみ: `pip install playwright` の後に `playwright install` を実行してください。

def _extract_events_from_json_payload(payload: Any) -> List[Dict[str, str]]:
    """
    JSONペイロードの中からイベントらしきエントリを抽出する。
    想定キー: title/name, startDate/start/endDate/end/period など。
    """
    results: List[Dict[str, str]] = []

    def walk(x: Any):
        if isinstance(x, dict):
            # イベント候補: タイトル相当 + 日付情報を含むもの
            keys = set(k.lower() for k in x.keys())
            title = x.get("title") or x.get("name") or x.get("headline")
            # 開始・終了・期間っぽいキー
            start = x.get("startDate") or x.get("start") or x.get("starts") or x.get("start_time")
            end = x.get("endDate") or x.get("end") or x.get("ends") or x.get("end_time")
            period = x.get("period") or x.get("dateRange") or x.get("dates")

            if title and (start or end or period):
                # 文字列化
                if not period:
                    # どちらかあれば期間文字列を作る
                    s = str(start) if start else ""
                    e = str(end) if end else ""
                    if s and e:
                        period = f"{s} ～ {e}"
                    else:
                        period = s or e
                results.append({
                    "title": str(title).strip(),
                    "period": str(period).strip(),
                })

            # 深掘り
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(payload)
    return results

def _extract_events_from_dom(page) -> List[Dict[str, str]]:
    """DOMからイベントのタイトルと期間らしきテキストを抽出（複数候補セレクタでフォールバック）。"""
    results: List[Dict[str, str]] = []
    candidate_selectors = [
        # よくあるカードリスト
        "article, li[role='listitem'], .card, .news-card, .event-card",
        # Astroの島内で使われがちなリストラッパ
        "[class*='news'], [class*='list'], [class*='event']"
    ]
    for sel in candidate_selectors:
        try:
            elements = page.locator(sel)
            count = elements.count()
            for i in range(min(count, 50)):
                el = elements.nth(i)
                text = el.inner_text().strip()
                # タイトル・期間をそれっぽく分離（見出し + 日付レンジ）
                # 見出し候補
                title = None
                for h in ["h1", "h2", "h3", "h4", "[class*='title']", "[class*='headline']"]:
                    try:
                        t = el.locator(h).first.inner_text().strip()
                        if t:
                            title = t
                            break
                    except Exception:
                        pass
                if not title:
                    # 最初の行をタイトル扱い
                    title = text.splitlines()[0][:120]

                # 期間候補（yyyy-mm-dd / yyyy.mm.dd / yyyy/mm/dd、日本語表記など）
                period_match = re.search(r"(\d{4}[./-]\d{1,2}[./-]\d{1,2}).{0,5}[〜~\-～ーtoTO ]{1,5}.{0,5}(\d{4}[./-]\d{1,2}[./-]\d{1,2})", text)
                if not period_match:
                    jp_date = re.search(r"(\d{4}年\s*\d{1,2}月\s*\d{1,2}日).*?(\d{4}年\s*\d{1,2}月\s*\d{1,2}日)", text)
                    if jp_date:
                        period = f"{jp_date.group(1)} ～ {jp_date.group(2)}"
                    else:
                        # 単独日付や月内表現だけでも拾う
                        one = re.search(r"(\d{4}[./-]\d{1,2}[./-]\d{1,2}|\d{4}年\s*\d{1,2}月\s*\d{1,2}日)", text)
                        period = one.group(1) if one else None
                else:
                    period = f"{period_match.group(1)} ～ {period_match.group(2)}"

                if title and period:
                    results.append({"title": title, "period": period})
        except Exception:
            continue
    # 重複排除
    uniq = []
    seen = set()
    for e in results:
        key = (e["title"], e["period"])
        if key not in seen:
            seen.add(key)
            uniq.append(e)
    return uniq

def _parse_period_to_dates(period: str):
    """期間文字列を start_date/end_date(YYYY-MM-DD) に正規化。失敗時はNoneを返す。"""
    def norm(y, m, d):
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"

    # 1) 2025-09-01 ～ 2025-09-15 / 2025.9.1 ～ 2025.9.15 / 2025/9/1 ～ 2025/9/15
    m = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2}).{0,10}[〜~\-～ーtoTO ]{1,10}(\d{4})[./-](\d{1,2})[./-](\d{1,2})", period)
    if m:
        s = norm(m.group(1), m.group(2), m.group(3))
        e = norm(m.group(4), m.group(5), m.group(6))
        return s, e

    # 2) 日本語: 2025年9月1日 ～ 2025年9月15日
    m = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日.*?(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", period)
    if m:
        s = norm(m.group(1), m.group(2), m.group(3))
        e = norm(m.group(4), m.group(5), m.group(6))
        return s, e

    # 3) 単独日付
    m = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", period)
    if m:
        s = norm(m.group(1), m.group(2), m.group(3))
        return s, s
    m = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", period)
    if m:
        s = norm(m.group(1), m.group(2), m.group(3))
        return s, s

    return None

def fetch_events_from_api(targets_path: str, headless: bool = True, timeout_ms: int = 45000) -> str:
    """
    Playwrightで各アウトレットのイベント一覧ページをレンダリングし、
    ネットワークJSON応答とDOMの両方からイベントを抽出して、
    LLMに渡すためのテキストを生成する。
    さらに `sales.json` を `[{name, start_date, end_date}, ...]` 形式で上書き生成する。
    """
    print("--- ヘッドレスでイベント情報取得開始 (Playwright) ---")
    all_events_text: List[str] = []
    sales_rows: List[Dict[str, str]] = []

    try:
        with open(targets_path, 'r', encoding='utf-8') as f:
            targets = json.load(f)
    except FileNotFoundError:
        print(f"エラー: 設定ファイル '{targets_path}' が見つかりません。")
        return ""

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(user_agent=(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/124.0.0.0 Safari/537.36'
        ))

        for target in targets:
            center_id = target.get('id')
            center_name = target.get('name', center_id)
            url = f"https://www.premiumoutlets.co.jp/{center_id}/events/"
            outlet_text = [f"--- {center_name}のイベント情報 ---"]
            collected: List[Dict[str, str]] = []

            for attempt in range(2):
                if attempt:
                    print(f"再試行 {attempt}/{2-1}: {center_name}")
                try:
                    page = context.new_page()
                    json_payloads: List[Any] = []

                    def on_response(resp):
                        try:
                            ct = resp.headers.get('content-type', '')
                            if 'application/json' in ct:
                                # サイズの大きすぎるレスは無視
                                if resp.status in (200, 203) and (0 < resp.request.resource_type != 'image'):
                                    if 'yext' in resp.url or 'liveapi' in resp.url or 'search' in resp.url or 'entities' in resp.url:
                                        data = resp.json()
                                        json_payloads.append(data)
                        except Exception:
                            pass

                    page.on('response', on_response)

                    print(f"[{center_name}] の情報を取得中: {url}")
                    page.goto(url, timeout=timeout_ms)
                    # 初期レンダリングとクライアントサイド取得の完了待ち
                    try:
                        page.wait_for_load_state('networkidle', timeout=min(30000, timeout_ms))
                    except PlaywrightTimeoutError:
                        # 一部のサイトでnetworkidleに至らないことがあるため、フォールバック
                        page.wait_for_timeout(3000)

                    # JSONペイロードから抽出
                    for payload in json_payloads:
                        extracted = _extract_events_from_json_payload(payload)
                        collected.extend(extracted)

                    # DOMからも抽出（フォールバック）
                    dom_events = _extract_events_from_dom(page)
                    collected.extend(dom_events)

                    if not collected:
                        outlet_text.append("現在、対象となるイベント情報はありません。")
                    else:
                        # 重複排除
                        uniq = []
                        seen = set()
                        for e in collected:
                            key = (e.get('title', ''), e.get('period', ''))
                            if key not in seen and e.get('title') and e.get('period'):
                                seen.add(key)
                                uniq.append(e)

                        for e in uniq:
                            outlet_text.append(f"イベント名: {e['title']}, 期間: {e['period']}")
                            parsed = _parse_period_to_dates(e['period'])
                            if parsed:
                                s, ed = parsed
                                sales_rows.append({
                                    "name": f"{center_name}: {e['title']}",
                                    "start_date": s,
                                    "end_date": ed
                                })

                    all_events_text.append("\n".join(outlet_text))
                    page.close()
                    break
                except Exception as e:
                    try:
                        page.close()
                    except Exception:
                        pass
                    if attempt == 1:
                        err = f"エラー: [{center_name}] の取得に失敗しました: {e}"
                        print(err)
                        all_events_text.append(f"--- {center_name}の情報 ---\n{err}\n")

        context.close()
        browser.close()

    # sales.json を出力（create_ical_from_json がそのまま使える）
    try:
        with open(SALES_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(sales_rows, f, ensure_ascii=False, indent=2)
        print(f"'{SALES_JSON_PATH}' を {len(sales_rows)} 件で更新しました。")
    except Exception as e:
        print(f"エラー: sales.json の書き込みに失敗しました: {e}")

    print("--- 情報取得完了 (Playwright) ---\n")
    return "\n\n".join(all_events_text)

def create_ical_from_json(json_path, ical_path):
    """
    JSONファイルからセール情報を読み込み、iCalファイルを生成する関数
    (この関数は変更ありません)
    """
    cal = Calendar()
    cal.add('prodid', '-//Premium Outlets Sale Calendar//example.com//')
    cal.add('version', '2.0')
    cal.add('X-WR-CALNAME', 'プレミアム・アウトレット セール情報')
    cal.add('X-WR-TIMEZONE', 'Asia/Tokyo')

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            sales_data = json.load(f)
    except FileNotFoundError:
        print(f"エラー: データファイル '{json_path}' が見つかりません。iCalファイルは生成されません。")
        return

    for sale in sales_data:
        event = Event()
        event.add('summary', sale['name'])
        start_date = datetime.strptime(sale['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(sale['end_date'], '%Y-%m-%d').date() + timedelta(days=1)
        event.add('dtstart', start_date)
        event.add('dtend', end_date)
        event.add('uid', f"{sale['start_date']}-{sale['name']}@premiumoutlets.example.com")
        cal.add_component(event)

    output_dir = os.path.dirname(ical_path)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    with open(ical_path, 'wb') as f:
        f.write(cal.to_ical())
    print(f"'{ical_path}' が正常に生成されました。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Premium Outlets events to iCal")
    parser.add_argument("--targets", default="targets.json", help="targets.json path")
    parser.add_argument("--sales", default="sales.json", help="output sales json path")
    parser.add_argument("--out", default="dist/premium_outlets_sales.ics", help="output iCal path")
    parser.add_argument("--no-headless", action="store_true", help="run browser with visible UI (for debug)")
    parser.add_argument("--timeout-ms", type=int, default=45000, help="page goto timeout in ms")
    args = parser.parse_args()

    global SALES_JSON_PATH
    SALES_JSON_PATH = args.sales

    # --- フェーズ1: ヘッドレスで情報を取得（JSON/DOM併用） ---
    event_text_content = fetch_events_from_api(
        targets_path=args.targets,
        headless=(not args.no_headless),
        timeout_ms=args.timeout_ms,
    )

    # 次のフェーズで、このテキストをLLMに渡す
    print("--- LLMに渡すための整形済みテキスト ---")
    print(event_text_content)
    print("------------------------------------\n")

    # --- iCal生成処理 ---
    print("--- iCal生成処理開始 ---")
    # 既に fetch が sales.json を更新している前提だが、引数で場所を指定可能に
    output_ical_file = args.out
    create_ical_from_json(args.sales, output_ical_file)
