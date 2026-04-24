"""
Google Sheets と Google Drive への書き込み
ユーザーごとにシート（タブ）を自動作成する
"""
import io
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

import config

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_creds = Credentials.from_service_account_info(
    config.load_service_account_info(), scopes=_SCOPES
)

_gc = gspread.authorize(_creds)
_drive = build("drive", "v3", credentials=_creds, cache_discovery=False)


def _spreadsheet():
    return _gc.open_by_key(config.SPREADSHEET_ID)


def _normalize_sheet_name(username: str | None, user_id: int | None) -> str:
    """
    ユーザーごとのシート名を決める。
      - username があれば "@username"
      - なければ "id_123456789"
      - どちらもなければ "unknown"
    """
    if username:
        # @ が付いていなければ付ける（統一）
        if not username.startswith("@"):
            username = "@" + username
        # シート名に使えない文字を置換（Googleの制限）
        for bad in "/\\[]*?:":
            username = username.replace(bad, "_")
        return username[:100]  # 念のため長さ制限
    if user_id is not None:
        return f"id_{user_id}"
    return "unknown"


def _get_or_create_user_sheet(sheet_name: str):
    """
    指定名のシートを取得。なければ作成してヘッダーも書き込む。
    """
    sh = _spreadsheet()
    try:
        ws = sh.worksheet(sheet_name)
        logger.info("Using existing sheet: %s", sheet_name)
        return ws
    except gspread.exceptions.WorksheetNotFound:
        pass

    # 新規作成（列数 = HEADERS の長さ、行数は多めに確保）
    ws = sh.add_worksheet(
        title=sheet_name,
        rows=1000,
        cols=len(config.SHEET_HEADERS),
    )
    # ヘッダー行を書き込み
    ws.append_row(config.SHEET_HEADERS, value_input_option="USER_ENTERED")
    logger.info("Created new sheet: %s", sheet_name)
    return ws


# ============================================================
# Google Drive
# ============================================================

def get_or_create_box_folder(box_number: str) -> str:
    """
    指定された箱番号のフォルダをDriveに作成（既にあれば再利用）。
    親フォルダ配下に「箱番号」という名前でフォルダを作る。
    フォルダIDを返す。
    """
    query = (
        f"'{config.DRIVE_PARENT_FOLDER_ID}' in parents "
        f"and name = '{box_number}' "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )
    resp = _drive.files().list(
        q=query,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]

    # 新規作成
    metadata = {
        "name": box_number,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [config.DRIVE_PARENT_FOLDER_ID],
    }
    folder = _drive.files().create(
        body=metadata, fields="id", supportsAllDrives=True
    ).execute()
    logger.info("Created Drive folder %s for box %s", folder["id"], box_number)
    return folder["id"]


def upload_photo(
    folder_id: str, filename: str, photo_bytes: bytes, mime_type: str = "image/jpeg"
) -> str:
    """
    写真をDriveにアップロードし、共有可能なリンクを返す
    """
    metadata = {"name": filename, "parents": [folder_id]}
    media = MediaIoBaseUpload(
        io.BytesIO(photo_bytes), mimetype=mime_type, resumable=False
    )
    file = _drive.files().create(
        body=metadata,
        media_body=media,
        fields="id, webViewLink",
        supportsAllDrives=True,
    ).execute()
    return file.get("webViewLink", "")


# ============================================================
# Google Sheets
# ============================================================

def append_row(data: dict, username: str | None = None, user_id: int | None = None) -> str:
    """
    出品1件分をユーザー専用シートに追記する。
    シートが存在しなければ自動で作成する。

    data の期待キー:
        box_number, hinshu, size, nedan, irisu, kibou_tanka, kuchisu,
        zentai_url, up_url

    戻り値: 書き込んだシート名
    """
    now = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S")

    sheet_name = _normalize_sheet_name(username, user_id)
    ws = _get_or_create_user_sheet(sheet_name)

    row = [
        now,
        data["box_number"],
        data["hinshu"],
        data["size"],
        data["nedan"],
        data["irisu"],
        data["kibou_tanka"],
        data["kuchisu"],
        data["zentai_url"],
        data["up_url"],
        "未出品",
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")
    logger.info(
        "Appended row to sheet='%s': box=%s hinshu=%s",
        sheet_name, data["box_number"], data["hinshu"]
    )
    return sheet_name
