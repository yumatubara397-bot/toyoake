"""
Google Sheets と Google Drive への書き込み
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


def _sheet():
    sh = _gc.open_by_key(config.SPREADSHEET_ID)
    return sh.worksheet(config.SHEET_NAME)


# ============================================================
# Google Drive
# ============================================================

def get_or_create_box_folder(box_number: str) -> str:
    """
    指定された箱番号のフォルダをDriveに作成（既にあれば再利用）。
    親フォルダ配下に「箱番号」という名前でフォルダを作る。
    フォルダIDを返す。
    """
    # 既存チェック
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

def append_row(data: dict) -> None:
    """
    出品1件分をスプレッドシートに追記する。
    dataの期待キー:
        box_number, hinshu, size, nedan, irisu, kibou_tanka, kuchisu,
        zentai_url, up_url
    """
    now = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S")

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
    _sheet().append_row(row, value_input_option="USER_ENTERED")
    logger.info("Appended row: box=%s hinshu=%s", data["box_number"], data["hinshu"])
