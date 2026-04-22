"""
Claude APIのVision機能を使って、箱の写真から箱番号を読み取る
"""
import base64
import logging
import re
from anthropic import Anthropic

import config

logger = logging.getLogger(__name__)

_client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

_PROMPT = """この画像には箱に印字された「箱番号」が写っています。
箱番号は最大8桁の英数字です。

画像から箱番号を読み取って、番号だけを返してください。
余計な説明は不要です。番号のみを返してください。

例: AB123456
例: 12345678

読み取れない場合は「UNREADABLE」と返してください。"""


def read_box_number(image_bytes: bytes, media_type: str = "image/jpeg") -> str | None:
    """
    画像バイト列から箱番号を読み取る。
    成功時: 正規化された箱番号（大文字英数字、最大8桁）
    失敗時: None
    """
    try:
        image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

        message = _client.messages.create(
            model="claude-opus-4-5",
            max_tokens=64,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
        )

        raw = message.content[0].text.strip().upper()
        logger.info("Claude OCR response: %r", raw)

        if "UNREADABLE" in raw:
            return None

        # 英数字のみ抽出、最大8桁
        cleaned = re.sub(r"[^A-Z0-9]", "", raw)
        if not cleaned:
            return None

        # 8桁を超えていたら先頭8桁を採用（保険）
        return cleaned[:8]

    except Exception as e:
        logger.exception("Claude Vision API呼び出しに失敗: %s", e)
        return None
