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
TELEGRAM_USER_ID = int(_get("TELEGRAM_USER_ID"))  # 許可する唯一のユーザー

# Anthropic
ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")

# Google
# Service AccountのJSONは、ファイルパスではなくJSON文字列そのものを環境変数に入れる
# (Railwayの環境変数は文字列のみ扱えるため)
GOOGLE_SERVICE_ACCOUNT_JSON = _get("GOOGLE_SERVICE_ACCOUNT_JSON")
SPREADSHEET_ID = _get("SPREADSHEET_ID")
DRIVE_PARENT_FOLDER_ID = _get("DRIVE_PARENT_FOLDER_ID")

# スプレッドシートのシート名（固定）
SHEET_NAME = "出品データ"

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
NEDAN_OPTIONS = [5000, 6000, 7000, 8000, 9000]
IRISU_OPTIONS = [72, 105, 128]
KUCHISU_OPTIONS = [1]


def load_service_account_info() -> dict:
    """環境変数からService AccountのJSONを辞書として読み込む"""
    try:
        return json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"GOOGLE_SERVICE_ACCOUNT_JSON が正しいJSONではありません: {e}")
