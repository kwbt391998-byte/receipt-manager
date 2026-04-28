from __future__ import annotations
import io
import re
from pathlib import Path
from typing import Optional

import pytesseract
from PIL import Image


def extract_receipt(file_path: str) -> dict:
    path = Path(file_path)

    if path.suffix.lower() == ".pdf":
        from pdf2image import convert_from_path
        images = convert_from_path(file_path, dpi=200)
        if not images:
            return _empty()
        img = images[0]
    else:
        img = Image.open(file_path)

    text = pytesseract.image_to_string(img, lang="jpn+eng")
    return _parse(text)


def _parse(text: str) -> dict:
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # ── 日付 ────────────────────────────────────────────────
    date = None
    for line in lines:
        m = re.search(r"(\d{4})[年/\-](\d{1,2})[月/\-](\d{1,2})", line)
        if m:
            date = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            break
        m = re.search(r"R(\d+)[年](\d{1,2})[月](\d{1,2})", line)
        if m:
            year = 2018 + int(m.group(1))
            date = f"{year:04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            break

    # ── 合計金額 ─────────────────────────────────────────────
    amount = None
    for pattern in [
        r"合計[^\d]*(\d[\d,]+)",
        r"税込[^\d]*(\d[\d,]+)",
        r"お支払[^\d]*(\d[\d,]+)",
        r"[¥￥]\s*(\d[\d,]+)",
    ]:
        for line in lines:
            m = re.search(pattern, line)
            if m:
                amount = _to_int(m.group(1))
                break
        if amount:
            break

    # ── 消費税 ───────────────────────────────────────────────
    tax = None
    for pattern in [r"消費税[^\d]*(\d[\d,]+)", r"税額[^\d]*(\d[\d,]+)"]:
        for line in lines:
            m = re.search(pattern, line)
            if m:
                tax = _to_int(m.group(1))
                break
        if tax:
            break

    # ── 支払先（最初の意味ある行） ───────────────────────────
    payee = None
    for line in lines[:8]:
        if len(line) >= 2 and not re.match(r"^[\d\s/年月日¥￥\-\.]+$", line):
            payee = line
            break

    return {
        "date": date,
        "payee": payee,
        "amount": amount,
        "tax_amount": tax,
        "purpose": None,
        "category": "その他",
        "memo": None,
    }


def _empty() -> dict:
    return {"date": None, "payee": None, "amount": None,
            "tax_amount": None, "purpose": None, "category": "その他", "memo": None}


def _to_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(str(val).replace(",", "").replace("円", "").strip())
    except (ValueError, TypeError):
        return None
