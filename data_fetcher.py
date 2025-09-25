import json
import requests

def fetch_events_from_api(targets_path):
    """
    設定ファイルに基づいてAPIからイベント情報を取得し、
    LLMに渡すための整形済みテキストを生成する関数。
    """
    print("--- APIからイベント情報取得開始 ---")
    all_events_text = []
    
    try:
        with open(targets_path, 'r', encoding='utf-8') as f:
            targets = json.load(f)
    except FileNotFoundError:
        print(f"エラー: 設定ファイル '{targets_path}' が見つかりません。")
        return ""

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    CATEGORY01_NEWS = 10  # プレミアム・アウトレットニュースカテゴリ
    CATEGORY02_PREMIUM_OUTLETS_NEWS = 200

    for target in targets:
        api_url = f"https://www.premiumoutlets.co.jp/api/v1/{target['id']}/news"

        try:
            print(f"[{target['name']}] の情報を取得中: {api_url}")
            response = requests.get(api_url, headers=headers, timeout=15)
            response.raise_for_status()

            events_data = response.json()
            news_items = events_data.get('news', []) if isinstance(events_data, dict) else []

            outlet_text = f"--- {target['name']}のイベント情報 ---\n"
            found_events = False

            for news in news_items:
                if not isinstance(news, dict):
                    continue

                if news.get('category01') != CATEGORY01_NEWS:
                    continue

                if news.get('category02') != CATEGORY02_PREMIUM_OUTLETS_NEWS:
                    continue

                title = (news.get('title') or '').strip()
                period = (news.get('schedule') or news.get('period') or '').strip()

                if not title or not period:
                    continue

                outlet_text += f"イベント名: {title}, 期間: {period}\n"
                found_events = True

            if not found_events:
                outlet_text += "現在、対象となるイベント情報はありません。\n"

            all_events_text.append(outlet_text)

        except requests.exceptions.RequestException as e:
            error_msg = f"エラー: [{target['name']}] のAPIアクセスに失敗しました。: {e}"
            print(error_msg)
            all_events_text.append(f"--- {target['name']}の情報 ---\n{error_msg}\n")
    
    print("--- 情報取得完了 ---\n")
    return "\n".join(all_events_text)
