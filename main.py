# 他の自作モジュールから必要な関数をインポート
import sys

from data_fetcher import fetch_events_from_api
from ical_generator import create_ical_from_json
from llm_parser import LLMParserError, export_events_to_json

if __name__ == "__main__":
    # --- STEP 1: APIから情報を取得 ---
    targets_file = 'targets.json'
    event_text_content = fetch_events_from_api(targets_file)

    print("--- LLMに渡すための整形済みテキスト ---")
    print(event_text_content)
    print("------------------------------------\n")

    # --- STEP 2: LLMで情報をJSONに変換 ---
    generated_json_file = 'dist/generated_events.json'
    try:
        events = export_events_to_json(event_text_content, generated_json_file)
    except LLMParserError as exc:
        print(f"エラー: LLMによるイベント抽出に失敗しました: {exc}")
        sys.exit(1)

    print(f"LLMが {len(events)} 件のイベントを抽出し、'{generated_json_file}' に保存しました。\n")

    # --- STEP 3: JSONデータからiCalファイルを生成 ---
    output_ical_file = 'dist/premium_outlets_sales.ics'
    create_ical_from_json(generated_json_file, output_ical_file)
