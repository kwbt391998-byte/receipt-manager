from __future__ import annotations
import json
import os
from pathlib import Path

import gspread


def _get_client() -> gspread.Client:
    """
    認証優先順位:
    1. Streamlit Cloud の Secrets ([google_service_account] セクション)
    2. ローカルの service_account.json ファイル
    """
    # ── Streamlit Cloud (本番) ─────────────────────────────────
    try:
        import streamlit as st
        # AttrDict → 通常の dict に変換（json経由でネスト構造も安全に変換）
        info = json.loads(json.dumps(dict(st.secrets["google_service_account"])))
        return gspread.service_account_from_dict(info)
    except Exception:
        pass

    # ── ローカル開発用 ────────────────────────────────────────
    local_path = Path(__file__).parent / "service_account.json"
    if local_path.exists():
        return gspread.service_account(filename=str(local_path))

    raise RuntimeError(
        "Google 認証情報が見つかりません。\n"
        "【Streamlit Cloud】Secrets に [google_service_account] を設定してください。\n"
        "【ローカル】プロジェクトフォルダに service_account.json を置いてください。\n"
        "設定方法は .streamlit/secrets.toml.example を参照してください。"
    )


def export_to_sheet(
    rows: list[dict],
    spreadsheet_id: str,
    sheet_name: str = "領収書一覧",
) -> str:
    """領収書データを Google スプレッドシートに書き込む。URLを返す。"""
    gc = _get_client()
    ss = gc.open_by_key(spreadsheet_id)

    try:
        ws = ss.worksheet(sheet_name)
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(sheet_name, rows=len(rows) + 5, cols=10)

    header = ["ID", "日付", "支払先", "金額", "税額", "用途", "カテゴリー", "メモ", "登録番号", "ファイル名", "登録日"]
    data = [header]
    for r in rows:
        data.append([
            r.get("id", ""),
            r.get("date", ""),
            r.get("payee", ""),
            r.get("amount", ""),
            r.get("tax_amount", ""),
            r.get("purpose", ""),
            r.get("category", ""),
            r.get("memo", ""),
            r.get("invoice_number", ""),
            r.get("file_name", ""),
            r.get("created_at", ""),
        ])

    ws.update(values=data, range_name="A1")
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
