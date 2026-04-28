from __future__ import annotations
import csv
import io
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

# ローカル開発時は .env からAPIキーを読み込む（本番は Streamlit Secrets が使われる）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import pandas as pd
import streamlit as st

import db
import sheets as sheets_mod

# Streamlit Cloud ではファイルシステムが一時的なため /tmp を使用
RECEIPTS_DIR = Path(tempfile.gettempdir()) / "receipts_manager"
RECEIPTS_DIR.mkdir(exist_ok=True)

CATEGORIES = [
    "交通費", "消耗品", "通信費", "交際費",
    "研修費", "書籍代", "雑費", "医療費", "その他",
]

st.set_page_config(page_title="領収書管理", page_icon="🧾", layout="wide")

# ── スマホ対応CSS ────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* 狭い画面ではカラムを縦並びに */
@media (max-width: 640px) {
    [data-testid="column"] { min-width: 100% !important; float: none !important; }
}
/* ボタンを横幅いっぱいに（スマホでタップしやすく） */
.stButton > button { width: 100%; padding: 0.6rem; font-size: 1rem; }
/* アップロードエリアを大きく */
[data-testid="stFileUploader"] { padding: 1rem; }
/* フォーム入力を大きく */
.stTextInput input, .stNumberInput input, .stTextArea textarea {
    font-size: 1rem;
}
</style>
""", unsafe_allow_html=True)

db.init_db()


# ── Sidebar navigation ──────────────────────────────────────────────────────
page = st.sidebar.radio(
    "ページ",
    ["アップロード", "一覧・編集", "月別集計", "カテゴリー別集計", "年間集計", "エクスポート"],
)


# ── Helper ──────────────────────────────────────────────────────────────────
def fmt_yen(v) -> str:
    if v is None or v == "":
        return ""
    try:
        return f"¥{int(v):,}"
    except (ValueError, TypeError):
        return str(v)


def safe_int(v):
    try:
        return int(v) if v not in (None, "", "None") else None
    except (ValueError, TypeError):
        return None


# ════════════════════════════════════════════════════════════════════════════
# PAGE: アップロード
# ════════════════════════════════════════════════════════════════════════════
if page == "アップロード":
    st.title("🧾 領収書アップロード")

    uploaded = st.file_uploader(
        "領収書ファイルを選択（JPG / PNG / PDF）",
        type=["jpg", "jpeg", "png", "pdf"],
        accept_multiple_files=True,
    )

    if uploaded:
        for up_file in uploaded:
            st.divider()
            col_img, col_form = st.columns([1, 1])

            # キーはオリジナルのファイル名から生成（リラン時も変わらないよう固定）
            key = up_file.name.replace(".", "_").replace(" ", "_").replace("-", "_")

            # 保存先をsession_stateで固定（リランのたびにカウンターが増えるバグを防止）
            sp_key = f"save_path_{key}"
            if sp_key not in st.session_state:
                save_path = RECEIPTS_DIR / up_file.name
                counter = 1
                while save_path.exists():
                    stem = Path(up_file.name).stem
                    suffix = Path(up_file.name).suffix
                    save_path = RECEIPTS_DIR / f"{stem}_{counter}{suffix}"
                    counter += 1
                save_path.write_bytes(up_file.getvalue())
                st.session_state[sp_key] = save_path
            else:
                save_path = st.session_state[sp_key]
                if not save_path.exists():
                    save_path.write_bytes(up_file.getvalue())

            with col_img:
                if up_file.type != "application/pdf":
                    st.image(up_file, caption=up_file.name, use_container_width=True)
                else:
                    st.info(f"PDF: {up_file.name}")

            # Duplicate check
            existing = db.get_possible_duplicate(save_path.name, None)
            if existing:
                st.warning(
                    f"⚠️ 同名ファイルが既に登録されています: {', '.join(r['file_name'] for r in existing)}"
                )

            with col_form:
                with st.form(key=f"form_{key}"):
                    date    = st.text_input("日付 (YYYY-MM-DD)", placeholder="例: 2026-04-29")

                    # 支払先：過去の履歴から選択 or 新規入力
                    past_payees = db.get_unique_payees()
                    if past_payees:
                        payee_sel = st.selectbox("支払先（履歴から選択）", [""] + past_payees)
                        payee_new = st.text_input("または新規入力", placeholder="例: セブンイレブン")
                        payee = payee_new.strip() if payee_new.strip() else payee_sel
                    else:
                        payee = st.text_input("支払先", placeholder="例: セブンイレブン")

                    amount  = st.number_input("金額（円）", value=0, min_value=0)
                    tax     = st.number_input("税額（円）", value=0, min_value=0)
                    purpose = st.text_input("用途", placeholder="例: 文房具購入")
                    category = st.selectbox("カテゴリー", CATEGORIES)
                    memo    = st.text_area("メモ")

                    if st.form_submit_button("💾 保存"):
                        dup = db.get_possible_duplicate(save_path.name, amount or None)
                        if dup:
                            st.warning("⚠️ 同名または同金額の領収書が既に存在します。それでも保存しますか？")

                        db.insert_receipt(
                            file_name=save_path.name,
                            file_path=str(save_path),
                            date=date or None,
                            payee=payee or None,
                            amount=amount or None,
                            tax_amount=tax or None,
                            purpose=purpose or None,
                            category=category,
                            memo=memo or None,
                        )
                        st.success(f"✅ 保存しました: {save_path.name}")
                        # Clear OCR state
                        st.session_state.pop(f"ocr_{key}_data", None)


# ════════════════════════════════════════════════════════════════════════════
# PAGE: 一覧・編集
# ════════════════════════════════════════════════════════════════════════════
elif page == "一覧・編集":
    st.title("📋 領収書一覧")

    all_receipts = db.get_all_receipts()
    if not all_receipts:
        st.info("登録された領収書がありません。")
        st.stop()

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        year_opts = sorted({r["date"][:4] for r in all_receipts if r.get("date")}, reverse=True)
        year_filter = st.selectbox("年", ["全て"] + year_opts)
    with col2:
        cat_filter = st.selectbox("カテゴリー", ["全て"] + CATEGORIES)
    with col3:
        search = st.text_input("支払先・用途 検索")

    filtered = all_receipts
    if year_filter != "全て":
        filtered = [r for r in filtered if (r.get("date") or "").startswith(year_filter)]
    if cat_filter != "全て":
        filtered = [r for r in filtered if r.get("category") == cat_filter]
    if search:
        filtered = [
            r for r in filtered
            if search in (r.get("payee") or "") or search in (r.get("purpose") or "")
        ]

    st.caption(f"{len(filtered)} 件")

    for r in filtered:
        with st.expander(
            f"[{r.get('date', '日付不明')}] {r.get('payee', '支払先不明')}  {fmt_yen(r.get('amount'))}  {r.get('category', '')}",
            expanded=False,
        ):
            col_img, col_edit = st.columns([1, 1])

            with col_img:
                fp = Path(r.get("file_path", ""))
                if fp.exists() and fp.suffix.lower() in (".jpg", ".jpeg", ".png"):
                    st.image(str(fp), use_container_width=True)
                elif fp.exists() and fp.suffix.lower() == ".pdf":
                    st.info(f"PDF: {fp.name}")
                else:
                    st.caption("ファイルなし")

            with col_edit:
                eid = r["id"]
                with st.form(key=f"edit_{eid}"):
                    e_date    = st.text_input("日付", value=r.get("date") or "")
                    e_payee   = st.text_input("支払先", value=r.get("payee") or "")
                    e_amount  = st.number_input("金額", value=safe_int(r.get("amount")) or 0, min_value=0)
                    e_tax     = st.number_input("税額", value=safe_int(r.get("tax_amount")) or 0, min_value=0)
                    e_purpose = st.text_input("用途", value=r.get("purpose") or "")
                    cat_i     = CATEGORIES.index(r["category"]) if r.get("category") in CATEGORIES else 0
                    e_cat     = st.selectbox("カテゴリー", CATEGORIES, index=cat_i)
                    e_memo    = st.text_area("メモ", value=r.get("memo") or "")

                    col_s, col_d = st.columns(2)
                    with col_s:
                        if st.form_submit_button("💾 更新"):
                            db.update_receipt(
                                eid, e_date or None, e_payee or None,
                                e_amount or None, e_tax or None,
                                e_purpose or None, e_cat, e_memo or None,
                            )
                            st.success("更新しました")
                            st.rerun()
                    with col_d:
                        if st.form_submit_button("🗑 削除", type="secondary"):
                            db.delete_receipt(eid)
                            st.success("削除しました")
                            st.rerun()


# ════════════════════════════════════════════════════════════════════════════
# PAGE: 月別集計
# ════════════════════════════════════════════════════════════════════════════
elif page == "月別集計":
    st.title("📅 月別集計")

    all_receipts = db.get_all_receipts()
    dated = [r for r in all_receipts if r.get("date")]
    if not dated:
        st.info("日付付きの領収書がありません。")
        st.stop()

    year_opts = sorted({r["date"][:4] for r in dated}, reverse=True)
    year = st.selectbox("年", year_opts)
    recs = [r for r in dated if r["date"].startswith(year)]

    df = pd.DataFrame(recs)
    df["month"] = df["date"].str[:7]
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)

    monthly = df.groupby("month")["amount"].sum().reset_index()
    monthly.columns = ["年月", "合計金額"]
    monthly["合計金額（表示）"] = monthly["合計金額"].apply(lambda x: f"¥{int(x):,}")

    st.dataframe(monthly[["年月", "合計金額（表示）"]], use_container_width=True, hide_index=True)
    st.bar_chart(monthly.set_index("年月")["合計金額"])

    st.caption(f"年間合計: ¥{int(df['amount'].sum()):,}")


# ════════════════════════════════════════════════════════════════════════════
# PAGE: カテゴリー別集計
# ════════════════════════════════════════════════════════════════════════════
elif page == "カテゴリー別集計":
    st.title("🗂 カテゴリー別集計")

    all_receipts = db.get_all_receipts()
    if not all_receipts:
        st.info("登録された領収書がありません。")
        st.stop()

    year_opts = sorted({r["date"][:4] for r in all_receipts if r.get("date")}, reverse=True)
    year = st.selectbox("年", ["全て"] + year_opts)

    recs = all_receipts if year == "全て" else [r for r in all_receipts if (r.get("date") or "").startswith(year)]

    df = pd.DataFrame(recs)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    df["category"] = df["category"].fillna("その他")

    by_cat = df.groupby("category")["amount"].sum().reset_index()
    by_cat.columns = ["カテゴリー", "合計金額"]
    by_cat = by_cat.sort_values("合計金額", ascending=False)
    by_cat["合計金額（表示）"] = by_cat["合計金額"].apply(lambda x: f"¥{int(x):,}")

    st.dataframe(by_cat[["カテゴリー", "合計金額（表示）"]], use_container_width=True, hide_index=True)
    st.bar_chart(by_cat.set_index("カテゴリー")["合計金額"])

    total = int(df["amount"].sum())
    st.caption(f"合計: ¥{total:,}")


# ════════════════════════════════════════════════════════════════════════════
# PAGE: 年間集計
# ════════════════════════════════════════════════════════════════════════════
elif page == "年間集計":
    st.title("📊 年間集計")

    all_receipts = db.get_all_receipts()
    dated = [r for r in all_receipts if r.get("date")]
    if not dated:
        st.info("日付付きの領収書がありません。")
        st.stop()

    year_opts = sorted({r["date"][:4] for r in dated}, reverse=True)
    year = st.selectbox("年", year_opts)
    recs = [r for r in dated if r["date"].startswith(year)]

    df = pd.DataFrame(recs)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    df["tax_amount"] = pd.to_numeric(df["tax_amount"], errors="coerce").fillna(0)
    df["category"] = df["category"].fillna("その他")

    col1, col2, col3 = st.columns(3)
    col1.metric("件数", f"{len(recs)} 件")
    col2.metric("合計金額", f"¥{int(df['amount'].sum()):,}")
    col3.metric("合計税額", f"¥{int(df['tax_amount'].sum()):,}")

    st.subheader("カテゴリー別")
    by_cat = df.groupby("category")["amount"].sum().sort_values(ascending=False)
    st.bar_chart(by_cat)

    st.subheader("月別推移")
    df["month"] = df["date"].str[:7]
    by_month = df.groupby("month")["amount"].sum()
    st.bar_chart(by_month)

    st.subheader("明細")
    display = df[["date", "payee", "amount", "tax_amount", "purpose", "category"]].copy()
    display.columns = ["日付", "支払先", "金額", "税額", "用途", "カテゴリー"]
    st.dataframe(display, use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════════════════════════
# PAGE: エクスポート
# ════════════════════════════════════════════════════════════════════════════
elif page == "エクスポート":
    st.title("📤 エクスポート")

    all_receipts = db.get_all_receipts()
    if not all_receipts:
        st.info("登録された領収書がありません。")
        st.stop()

    year_opts = sorted({r["date"][:4] for r in all_receipts if r.get("date")}, reverse=True)
    year = st.selectbox("対象年", ["全て"] + year_opts)
    recs = all_receipts if year == "全て" else [r for r in all_receipts if (r.get("date") or "").startswith(year)]

    st.caption(f"{len(recs)} 件対象")

    # ── CSV export ──────────────────────────────────────────────────────────
    st.subheader("CSV ダウンロード")
    if st.button("CSVを生成"):
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf,
            fieldnames=["id", "date", "payee", "amount", "tax_amount", "purpose", "category", "memo", "file_name", "created_at"],
        )
        writer.writeheader()
        for r in recs:
            writer.writerow({k: r.get(k, "") for k in writer.fieldnames})

        st.download_button(
            label="⬇️ CSVダウンロード",
            data=buf.getvalue().encode("utf-8-sig"),
            file_name=f"receipts_{year}_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )

    st.divider()

    # ── Google Sheets export ─────────────────────────────────────────────────
    st.subheader("Google スプレッドシートへ書き込み")
    ss_id = st.text_input(
        "スプレッドシートID",
        placeholder="1xxxx...（URLの /d/ と /edit の間の文字列）",
    )
    sheet_name = st.text_input("シート名", value="領収書一覧")

    if st.button("📊 Sheetsへ書き込み"):
        if not ss_id.strip():
            st.error("スプレッドシートIDを入力してください。")
        else:
            try:
                url = sheets_mod.export_to_sheet(recs, ss_id.strip(), sheet_name)
                st.success(f"✅ 書き込み完了: [スプレッドシートを開く]({url})")
            except Exception as e:
                st.error(f"エラー: {e}")
