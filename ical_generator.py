import json
from datetime import datetime, timedelta
from icalendar import Calendar, Event
import os

def create_ical_from_json(json_path, ical_path):
    """
    JSON形式のデータからiCalファイルを生成する関数。
    """
    print("--- iCal生成処理開始 ---")
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
        # 終日イベントとして扱うため、終了日の翌日を dtend に設定
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

