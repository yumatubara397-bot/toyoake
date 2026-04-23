"""
Phase 2 Worker - 設定
品種コード、ログイン情報、URLなどの定数を定義
"""
import os
from datetime import datetime, timedelta

# ==================== イロドリミドリ 認証情報 ====================
IM_LOGIN_URL = "https://im.toyoake.jp/"
IM_USER_ID = os.getenv("IM_USER_ID", "tensawa0")
IM_PASSWORD = os.getenv("IM_PASSWORD", "tensawa3350002")

# ==================== URL ====================
IM_OKURI_URL = "https://im.toyoake.jp/shukka/okuri/index.cfm"
IM_SEARCH_URL = (
    "https://im.toyoake.jp/shukka/okuri/index.cfm"
    "?fuseaction=GoodsSrchSub&TextName=HknsakKana&TextCode=HinmeiCd&FuncName=GoChange"
)

# ==================== 品種コード表 ====================
# スプレッドシートのC列「品種」に入る値から、イロドリミドリの品名コードへ変換
HINMEI_CODE_MAP = {
    "タニクショクブツ": "089130",
    "エケベリア":      "020951",
    "セダム":          "021002",
    "アエオニウム":    "020939",
    "アドロミスクス":  "080680",
    "クラッスラ":      "020943",
}

# ==================== サイズ固定 ====================
DEFAULT_SIZE = "99.0"  # プルダウンの選択肢

# ==================== 開市日ルール ====================
def get_next_market_date(today: datetime | None = None) -> str:
    """
    次の開市日を返す。開市日は月曜(0)と木曜(3)に固定。

    ルール:
      - 今日が月曜または木曜なら今日
      - それ以外は直近の次の月曜または木曜
    戻り値: "YYYY/MM/DD(曜)" 形式（イロドリミドリの日付ピッカーに入れる形式）
    """
    if today is None:
        today = datetime.now()
    today = today.replace(hour=0, minute=0, second=0, microsecond=0)

    MARKET_DAYS = [0, 3]  # 月曜=0, 木曜=3
    for offset in range(0, 8):
        candidate = today + timedelta(days=offset)
        if candidate.weekday() in MARKET_DAYS:
            return candidate.strftime("%Y/%m/%d") + f"({'月火水木金土日'[candidate.weekday()]})"
    return today.strftime("%Y/%m/%d")  # fallback

# ==================== テストモード ====================
# True の場合、登録ボタンを押す直前で止めて確認ショット保存
# False の場合、本番登録を実行
SHUKKA_DRY_RUN = os.getenv("SHUKKA_DRY_RUN", "false").lower() == "true"

# ==================== タイムアウト ====================
DEFAULT_TIMEOUT = 30000  # 30秒

# ==================== スクリーンショット保存先 ====================
SCREENSHOT_DIR = "/tmp/shukka_shots"
