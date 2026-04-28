from __future__ import annotations
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional

DB_PATH = Path(__file__).parent / "receipts.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS receipts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name   TEXT    NOT NULL,
                file_path   TEXT    NOT NULL,
                date        TEXT,
                payee       TEXT,
                amount      INTEGER,
                tax_amount  INTEGER,
                purpose     TEXT,
                category    TEXT,
                memo        TEXT,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
                updated_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """)
        conn.commit()


def insert_receipt(
    file_name: str,
    file_path: str,
    date: Optional[str] = None,
    payee: Optional[str] = None,
    amount: Optional[int] = None,
    tax_amount: Optional[int] = None,
    purpose: Optional[str] = None,
    category: Optional[str] = None,
    memo: Optional[str] = None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO receipts
               (file_name, file_path, date, payee, amount, tax_amount, purpose, category, memo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (file_name, file_path, date, payee, amount, tax_amount, purpose, category, memo),
        )
        conn.commit()
        return cur.lastrowid


def update_receipt(
    receipt_id: int,
    date: Optional[str],
    payee: Optional[str],
    amount: Optional[int],
    tax_amount: Optional[int],
    purpose: Optional[str],
    category: Optional[str],
    memo: Optional[str],
) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE receipts SET
               date=?, payee=?, amount=?, tax_amount=?, purpose=?, category=?, memo=?,
               updated_at=datetime('now','localtime')
               WHERE id=?""",
            (date, payee, amount, tax_amount, purpose, category, memo, receipt_id),
        )
        conn.commit()


def delete_receipt(receipt_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM receipts WHERE id=?", (receipt_id,))
        conn.commit()


def get_all_receipts() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM receipts ORDER BY date DESC, id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_receipt_by_id(receipt_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM receipts WHERE id=?", (receipt_id,)
        ).fetchone()
        return dict(row) if row else None


def get_receipts_by_year(year: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM receipts WHERE date LIKE ? ORDER BY date",
            (f"{year}-%",),
        ).fetchall()
        return [dict(r) for r in rows]


def get_possible_duplicate(file_name: str, amount: Optional[int]) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM receipts WHERE file_name=? OR (amount=? AND amount IS NOT NULL)",
            (file_name, amount),
        ).fetchall()
        return [dict(r) for r in rows]
