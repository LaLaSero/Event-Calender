import json
from datetime import datetime, timedelta
from icalendar import Calendar, Event
import os

def create_ical_from_json(json_path, ical_path):
    """
    JSONファイルからセール情報を読み込み、iCalファイルを生成する関数
    """
    # カレンダーオブジェクトを作成
    cal = Calendar()
    cal.add('prodid', '-//Premium Outlets Sale Calendar//example.com//')
    cal.add('version', '2.0')
    cal.add('X-WR-CALNAME', 'プレミアム・アウトレット セール情報') # カレンダー名
    cal.add('X-WR-TIMEZONE', 'Asia/Tokyo') # タイムゾーン

    # JSONファイルを読み込む
    with open(json_path, 'r', encoding='utf-8') as f:
        sales_data = json.load(f)

    for sale in sales_data:
        event = Event()
        event.add('summary', sale['name']) # イベントのタイトル

        # 終日イベントとして設定
        start_date = datetime.strptime(sale['start_date'], '%Y-%m-%d').date()
        # iCalの仕様では、終日イベントの終了日は最終日の翌日を指定する
        end_date = datetime.strptime(sale['end_date'], '%Y-%m-%d').date() + timedelta(days=1)
        
        event.add('dtstart', start_date)
        event.add('dtend', end_date)
        
        # ユニークなIDを設定
        event.add('uid', f"{sale['start_date']}-{sale['name']}@premiumoutlets.example.com")

        # イベントをカレンダーに追加
        cal.add_component(event)

    # iCalファイルを書き出すディレクトリを確認・作成
    output_dir = os.path.dirname(ical_path)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # iCalファイルに書き出す
    with open(ical_path, 'wb') as f:
        f.write(cal.to_ical())

    print(f"'{ical_path}' が正常に生成されました。")

if __name__ == "__main__":
    # JSONファイルのパス
    json_file = 'sales.json'
    # 出力するiCalファイルのパス (distディレクトリ内)
    ical_file = 'dist/premium_outlets_sales.ics'
    
    create_ical_from_json(json_file, ical_file)
