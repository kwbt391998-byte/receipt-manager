from __future__ import annotations
import base64
import json
import re
from pathlib import Path
from typing import Optional

import anthropic

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _encode_image(file_path: str) -> tuple[str, str]:
    """Returns (base64_data, media_type)"""
    path = Path(file_path)
    suffix = path.suffix.lower()
    media_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }
    media_type = media_map.get(suffix, "image/jpeg")
    with open(file_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8"), media_type


SYSTEM_PROMPT = """あなたは領収書OCRの専門家です。
画像から以下の情報を正確に読み取り、必ずJSONのみで返してください。
JSONのキーと値の形式:
{
  "date": "YYYY-MM-DD形式（不明はnull）",
  "payee": "支払先・店名（不明はnull）",
  "amount": 金額（税込の合計金額、整数、円単位、不明はnull）,
  "tax_amount": 消費税額（整数、円単位、不明はnull）,
  "purpose": "用途・品目の概要（不明はnull）",
  "category": "カテゴリー（交通費/消耗品/通信費/交際費/研修費/書籍代/雑費/医療費/その他 から最適なもの）",
  "memo": "その他メモや特記事項（なければnull）"
}
Markdown、コードブロック、説明文は不要です。JSONのみ返してください。"""


def extract_receipt(file_path: str) -> dict:
    """
    Returns dict with keys: date, payee, amount, tax_amount, purpose, category, memo
    All values may be None if not found.
    """
    client = _get_client()
    b64, media_type = _encode_image(file_path)

    if media_type == "application/pdf":
        content = [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": b64,
                },
            },
            {"type": "text", "text": "この領収書から情報を抽出してください。"},
        ]
    else:
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": b64,
                },
            },
            {"type": "text", "text": "この領収書から情報を抽出してください。"},
        ]

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}

    return {
        "date": data.get("date"),
        "payee": data.get("payee"),
        "amount": _to_int(data.get("amount")),
        "tax_amount": _to_int(data.get("tax_amount")),
        "purpose": data.get("purpose"),
        "category": data.get("category"),
        "memo": data.get("memo"),
    }


def _to_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(str(val).replace(",", "").replace("円", "").strip())
    except (ValueError, TypeError):
        return None
