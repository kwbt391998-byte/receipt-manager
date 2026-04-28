from __future__ import annotations
import io
import json
import os
import re
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

_client = None

PROMPT = """あなたは領収書OCRの専門家です。
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
Markdown、コードブロック、説明文は不要です。JSONのみ返してください。
この領収書から情報を抽出してください。"""


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            try:
                import streamlit as st
                api_key = st.secrets.get("GOOGLE_API_KEY")
            except Exception:
                pass
        if not api_key:
            raise ValueError("GOOGLE_API_KEY が設定されていません。Streamlit Secrets に追加してください。")
        _client = genai.Client(api_key=api_key)
    return _client


def extract_receipt(file_path: str) -> dict:
    client = _get_client()
    path = Path(file_path)

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    if path.suffix.lower() == ".pdf":
        part = types.Part.from_bytes(data=file_bytes, mime_type="application/pdf")
    else:
        import PIL.Image
        img = PIL.Image.open(io.BytesIO(file_bytes))
        part = img

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[part, PROMPT],
    )

    raw = response.text.strip()
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
