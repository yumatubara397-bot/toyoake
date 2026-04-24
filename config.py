"""
設定値の読み込み
環境変数から全ての秘匿情報を取得する。
Railwayの環境変数にこれらを設定しておくこと。
"""
import os
import json
from pathlib import Path


def _get(name: str, required: bool = True) -> str:
    value = os.environ.get(name, "").strip()
    if required and not value:
        raise RuntimeError(f"環境変数 {name} が設定されていません")
    return value


# Telegram
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")

# TELEGRAM_USER_ID はオプション（空なら誰でも使える）
_user_id_raw = os.environ.get("TELEGRAM_USER_ID", "").strip()
TELEGRAM_USER_ID: int | None = int(_user_id_raw) if _user_id_raw else None

# Anthropic
ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")

# Google
GOOGLE_SERVICE_ACCOUNT_JSON = _get("GOOGLE_SERVICE_ACCOUNT_JSON")
SPREADSHEET_ID = _get("SPREADSHEET_ID")
DRIVE_PARENT_FOLDER_ID = _get("DRIVE_PARENT_FOLDER_ID")

# スプレッドシートのテンプレートシート名（ヘッダーのお手本）
# これが存在すればヘッダーをコピーしてユーザー用シートを作る
TEMPLATE_SHEET_NAME = "出品データ"

# シートのヘッダー列（全11列）
SHEET_HEADERS = [
    "タイムスタンプ",
    "箱番号",
    "品種",
    "サイズ",
    "値段",
    "入数",
    "希望単価",
    "口数",
    "全体写真",
    "アップ写真",
    "出品ステータス",
]

# 選択肢マスタ
HINSHU_LIST = [
    "タニクショクブツ",
    "エケベリア",
    "セダム",
    "アエオニウム",
    "アドロミスクス",
    "クラッスラ",
    "グラプトペダルム",
    "ハオルシア",
    "パキフィッツム",
]

SIZE_OPTIONS = ["99.0"]
NEDAN_OPTIONS = [5000, 5500, 6000, 7000, 8000, 9000]
# 拡張: 16/20/32/50/54/72/78/105/128 の昇順
IRISU_OPTIONS = [16, 20, 32, 50, 54, 72, 78, 105, 128]
KUCHISU_OPTIONS = [1]


def load_service_account_info() -> dict:
    """環境変数からService AccountのJSONを辞書として読み込む"""
    try:
        return json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"GOOGLE_SERVICE_ACCOUNT_JSON が正しいJSONではありません: {e}")
