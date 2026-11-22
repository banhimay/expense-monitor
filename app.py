"""Expense Monitor — daily household expense book with monthly Word file and custom reports.
Same pattern as the Equity Portfolio app: Streamlit + Postgres (DATABASE_URL) + password (EXPENSE_PASSWORD).
Without DATABASE_URL it uses a local SQLite file, for testing on your own computer."""
import json
import os
import re
import sqlite3
import calendar
from io import BytesIO
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st


def detect_mobile():
    try:
        forced = st.query_params.get("view")
        if forced in ("mobile", "desktop"):
            return forced == "mobile"
        ua = st.context.headers.get("User-Agent", "") or ""
        return bool(re.search(r"Mobile|Android|iPhone|iPod", ua, re.I))
    except Exception:
        return False


IS_MOBILE = detect_mobile()
st.set_page_config(page_title="Expense Monitor", page_icon="₹", layout="wide",
                   initial_sidebar_state="collapsed")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
PASSWORD = os.environ.get("EXPENSE_PASSWORD", "admin")
SQLITE_FILE = os.environ.get("SQLITE_FILE", "expenses.db")
SEED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_sep_oct_2026.json")

DEFAULT_CATS = [
    ("edu", "Children's education", True),
    ("emi", "Loans & EMIs", True),
    ("home", "Household & groceries", True),
    ("help", "Domestic help & family", True),
    ("med", "Medical", True),
    ("travel", "Travel & commute", True),
    ("office", "Office", True),
    ("fest", "Festivals, gifts & donations", True),
    ("food", "Eating out", True),
    ("shop", "Shopping & personal", True),
    ("subs", "Subscriptions & learning", True),
    ("other", "Others", True),
    ("card", "Credit card bill (not counted)", False),
]
MONTHS = list(calendar.month_name)[1:]


# ---------------- login ----------------
def check_password():
    if st.session_state.get("authenticated"):
        return True
    st.title("🔒 Expense Monitor")
    with st.form("login"):
        pwd = st.text_input("Enter password", type="password")
        if st.form_submit_button("Login", type="primary"):
            if pwd == PASSWORD:
                st.session_state["authenticated"] = True
                st.rerun()
            st.error("Incorrect password.")
    return False


if not check_password():
    st.stop()


# ---------------- database ----------------
def db_connect():
    if DATABASE_URL:
        import psycopg2
        return psycopg2.connect(DATABASE_URL, connect_timeout=10)
    return sqlite3.connect(SQLITE_FILE)


def run(sql, params=(), fetch=False, many=False):
    """One statement. Write SQL with %s placeholders; converted for SQLite."""
    if not DATABASE_URL:
        sql = sql.replace("%s", "?")
    con = db_connect()
    try:
        cur = con.cursor()
        if many:
            cur.executemany(sql, params)
        else:
            cur.execute(sql, params)
        rows = cur.fetchall() if fetch else None
        con.commit()
        return rows
    finally:
        con.close()


@st.cache_resource
def db_init():
    idcol = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    run(f"""CREATE TABLE IF NOT EXISTS expenses (
        id {idcol}, d DATE NOT NULL, amount INTEGER NOT NULL, cat TEXT NOT NULL,
        note TEXT DEFAULT '', fixed BOOLEAN DEFAULT FALSE, created_at TEXT)""")
    run("""CREATE TABLE IF NOT EXISTS categories (
        key TEXT PRIMARY KEY, label TEXT NOT NULL, counted BOOLEAN DEFAULT TRUE, sort INTEGER DEFAULT 0)""")
    if not run("SELECT COUNT(*) FROM categories", fetch=True)[0][0]:
        run("INSERT INTO categories (key, label, counted, sort) VALUES (%s,%s,%s,%s)",
            [(k, l, c, i) for i, (k, l, c) in enumerate(DEFAULT_CATS)], many=True)
    if not run("SELECT COUNT(*) FROM expenses", fetch=True)[0][0] and os.path.exists(SEED_FILE):
        seed = json.load(open(SEED_FILE, encoding="utf-8"))
        rows = [(e["d"], int(e["a"]), e["c"], e.get("n", ""), bool(e.get("r")), "seed")
                for m in seed.values() for e in m["entries"]]
        run("INSERT INTO expenses (d, amount, cat, note, fixed, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
            rows, many=True)
    return True


db_init()


def load_cats():
    rows = run("SELECT key, label, counted, sort FROM categories ORDER BY sort, label", fetch=True)
    return pd.DataFrame(rows, columns=["key", "label", "counted", "sort"]).assign(counted=lambda x: x.counted.astype(bool))


def load_expenses():
    rows = run("SELECT id, d, amount, cat, note, fixed FROM expenses ORDER BY d, id", fetch=True)
    df = pd.DataFrame(rows, columns=["id", "d", "amount", "cat", "note", "fixed"])
    if df.empty:
        df["d"] = pd.to_datetime(df["d"])
        return df
    df["d"] = pd.to_datetime(df["d"])
    df["amount"] = df["amount"].astype(int)
    df["fixed"] = df["fixed"].astype(bool)
    df["note"] = df["note"].fillna("")
    df["month"] = df["d"].dt.strftime("%Y-%m")
    return df


def add_expense(d, amount, cat, note, fixed):
    run("INSERT INTO expenses (d, amount, cat, note, fixed, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
        (d.isoformat(), int(amount), cat, note.strip(), bool(fixed), datetime.now().isoformat(timespec="seconds")))


# ---------------- helpers ----------------
def inr(n):
    n = int(round(n))
    s = str(abs(n))
    if len(s) > 3:
        s = _indian(s[:-3]) + "," + s[-3:]
    return ("−" if n < 0 else "") + "₹" + s


def _indian(head):
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts)


def mlabel(m):
    y, mm = m.split("-")
    return f"{MONTHS[int(mm) - 1]} {y}"


def counted_keys(cats):
    return set(cats.loc[cats.counted, "key"])


def with_labels(df, cats):
    lab = dict(zip(cats.key, cats.label))
    out = df.copy()
    out["category"] = out["cat"].map(lambda k: lab.get(k, k))
    return out


CSS = """<style>
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:4px 0 12px}
.kpi{border:1px solid rgba(128,128,128,.3);border-radius:10px;padding:10px 12px}
.kpi .l{font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;opacity:.7;font-weight:600}
.kpi .v{font-size:1.25rem;font-weight:600;font-variant-numeric:tabular-nums}
.kpi .s{font-size:.8rem;opacity:.7}
.dayhead{display:flex;justify-content:space-between;font-weight:600;font-size:.85rem;opacity:.8;border-bottom:1px solid rgba(128,128,128,.3);margin-top:10px}
</style>"""
st.markdown(CSS, unsafe_allow_html=True)


def kpis(items):
    html = "".join(f'<div class="kpi"><div class="l">{l}</div><div class="v">{v}</div><div class="s">{s}</div></div>'
                   for l, v, s in items)
    st.markdown(f'<div class="kpi-grid">{html}</div>', unsafe_allow_html=True)


# ---------------- Word file ----------------
def fmt_amt(a):
    return f"{int(a)}/-"


def build_word(month, df, cats):
    """Day-wise Word file in the same style as the handwritten logs, plus a category summary."""
    from docx import Document
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    y, m = map(int, month.split("-"))
    mdf = df[df.month == month]
    lab = dict(zip(cats.key, cats.label))
    ck = counted_keys(cats)
    doc = Document()
    st_ = doc.styles["Normal"]
    st_.font.name = "Calibri"
    st_.font.size = Pt(11)
    doc.add_heading(f"{MONTHS[m - 1]} {y}", level=1)
    for day in range(1, calendar.monthrange(y, m)[1] + 1):
        dd = mdf[mdf.d.dt.day == day]
        p = doc.add_paragraph()
        p.add_run(f"{day}/{m}/{str(y)[2:]} - ").bold = True
        if dd.empty:
            p.add_run("NIL")
        else:
            bits = []
            for r in dd.itertuples(index=False):
                t = f"{r.note or lab.get(r.cat, r.cat)} {fmt_amt(r.amount)}"
                bits.append(f"({t})" if r.cat not in ck else t)
            p.add_run(" ".join(bits))
            day_total = dd[dd.cat.isin(ck)].amount.sum()
            if len(dd) > 1 and day_total:
                p.add_run(f"   [day total {fmt_amt(day_total)}]").italic = True
        p.paragraph_format.space_after = Pt(4)

    doc.add_heading("Summary by head", level=2)
    t = mdf.groupby("cat").amount.sum()
    order = [k for k in cats.key if k in t.index]
    table = doc.add_table(rows=1, cols=3)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    hdr[0].text, hdr[1].text, hdr[2].text = "Head", "Amount (₹)", "Share"
    total = int(t[[k for k in order if k in ck]].sum()) if order else 0
    for k in order:
        c = table.add_row().cells
        c[0].text = lab.get(k, k)
        c[1].text = f"{int(t[k]):,}"
        c[2].text = f"{t[k] / total * 100:.1f}%" if (k in ck and total) else "not counted"
    c = table.add_row().cells
    c[0].text, c[1].text, c[2].text = "Total spent", f"{total:,}", "100%"
    for row in table.rows:
        for i in (1, 2):
            row.cells[i].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for cell in table.rows[-1].cells:
        for r in cell.paragraphs[0].runs:
            r.bold = True
    doc.add_paragraph(f"Generated by Expense Monitor on {datetime.now():%d %b %Y}.").runs[0].italic = True
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_report_word(title, sub, rdf, cats):
    from docx import Document
    lab = dict(zip(cats.key, cats.label))
    doc = Document()
    doc.add_heading(title, level=1)
    doc.add_paragraph(sub)
    table = doc.add_table(rows=1, cols=4)
    table.style = "Light Grid Accent 1"
    for c, h in zip(table.rows[0].cells, ["Date", "Head", "What for", "Amount (₹)"]):
        c.text = h
    for r in rdf.sort_values("d").itertuples(index=False):
        c = table.add_row().cells
        c[0].text, c[1].text, c[2].text, c[3].text = r.d.strftime("%d-%m-%Y"), lab.get(r.cat, r.cat), r.note, f"{int(r.amount):,}"
    c = table.add_row().cells
    c[2].text, c[3].text = "Total", f"{int(rdf.amount.sum()):,}"
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_excel(df, cats):
    lab = dict(zip(cats.key, cats.label))
    ck = counted_keys(cats)
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        if not df.empty:
            piv = df.pivot_table(index="cat", columns="month", values="amount", aggfunc="sum", fill_value=0)
            piv = piv.reindex([k for k in cats.key if k in piv.index])
            piv.index = [lab.get(k, k) for k in piv.index]
            tot = df[df.cat.isin(ck)].groupby("month").amount.sum()
            piv.loc["Total spent (excl. card bills)"] = tot
            piv.columns = [mlabel(c) for c in piv.columns]
            piv.to_excel(xw, sheet_name="Summary")
            for mth in sorted(df.month.unique()):
                x = df[df.month == mth][["d", "cat", "note", "amount", "fixed"]].copy()
                x["d"] = x.d.dt.date
                x["cat"] = x.cat.map(lambda k: lab.get(k, k))
                x.columns = ["Date", "Head", "What for", "Amount", "Fixed monthly"]
                x.to_excel(xw, sheet_name=mlabel(mth)[:31], index=False)
    return buf.getvalue()


# ---------------- app ----------------
cats = load_cats()
df = load_expenses()
CK = counted_keys(cats)
LAB = dict(zip(cats.key, cats.label))
cat_keys = list(cats.key)
today = date.today()
this_month = today.strftime("%Y-%m")
all_months = sorted(set(df.month) | {this_month}) if not df.empty else [this_month]

h1, h2 = st.columns([5, 1], vertical_alignment="center")
h1.title("₹ Expense Monitor")
if h2.button("🔒 Logout", key="logout_btn", width="stretch"):
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()
PAGES = ["➕ Add", "📒 Day book", "📊 Reports", "📄 Word file", "⚙️ Settings"]
page = st.pills("Menu", PAGES, selection_mode="single", key="nav", default=PAGES[0], label_visibility="collapsed") or PAGES[0]


def month_picker(key, default=None):
    opts = all_months[::-1]
    d = default or this_month
    return st.selectbox("Month", opts, index=opts.index(d) if d in opts else 0, format_func=mlabel, key=key)


# ---- ADD ----
if page == "➕ Add":
    mdf = df[df.month == this_month] if not df.empty else df
    spent = mdf[mdf.cat.isin(CK)].amount.sum() if not mdf.empty else 0
    tdf = mdf[mdf.d.dt.date == today] if not mdf.empty else mdf
    kpis([("Today", inr(tdf[tdf.cat.isin(CK)].amount.sum() if not tdf.empty else 0), f"{len(tdf)} entries"),
          (f"{MONTHS[today.month - 1]} so far", inr(spent), f"{len(mdf)} entries"),
          ("Children's education", inr(mdf[mdf.cat == 'edu'].amount.sum() if not mdf.empty else 0), "this month")])

    # fixed monthly items
    prev_m = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    fixed_prev = df[(df.month == prev_m) & df.fixed] if not df.empty else df
    has_fixed = (not mdf.empty) and mdf.fixed.any()
    if not fixed_prev.empty and not has_fixed:
        with st.container(border=True):
            st.markdown(f"**Fixed monthly items** — {len(fixed_prev)} items from {mlabel(prev_m)}, "
                        f"total {inr(fixed_prev.amount.sum())}. Change any amount, untick what doesn't apply, then add.")
            fx = fixed_prev[["note", "cat", "amount"]].copy()
            fx.insert(0, "add", True)
            fx["cat"] = fx.cat.map(lambda k: LAB.get(k, k))
            ed = st.data_editor(fx, hide_index=True, width="stretch", key="fx_ed",
                                column_config={"add": st.column_config.CheckboxColumn("Add"),
                                               "note": "Item", "cat": st.column_config.TextColumn("Head", disabled=True),
                                               "amount": st.column_config.NumberColumn("Amount ₹", step=1)})
            if st.button(f"Add to {MONTHS[today.month - 1]} (dated 1st)", type="primary"):
                inv = {v: k for k, v in LAB.items()}
                rows = [(today.replace(day=1).isoformat(), int(r.amount), inv.get(r.cat, "other"), r.note, True,
                         datetime.now().isoformat(timespec="seconds")) for r in ed.itertuples() if r.add and r.amount]
                run("INSERT INTO expenses (d, amount, cat, note, fixed, created_at) VALUES (%s,%s,%s,%s,%s,%s)", rows, many=True)
                st.toast(f"Added {len(rows)} fixed items")
                st.rerun()

    st.subheader("Add expense")
    with st.form("add", clear_on_submit=True):
        c1, c2 = st.columns([1, 1])
        d = c1.date_input("Date", value=today, format="DD/MM/YYYY")
        amt = c2.number_input("Amount ₹", min_value=0, step=10, value=None, placeholder="0")
        note = st.text_input("What for", placeholder="e.g. Weekly market, Mithai school fees")
        cat = st.radio("Head", cat_keys, format_func=lambda k: LAB[k], horizontal=True, index=cat_keys.index("home") if "home" in cat_keys else 0)
        fixed = st.checkbox("Fixed monthly item (offered again next month)")
        if st.form_submit_button("Save expense", type="primary", width="stretch"):
            if not amt:
                st.error("Enter an amount.")
            else:
                add_expense(d, amt, cat, note or LAB[cat], fixed)
                st.toast(f"Saved {inr(amt)} · {LAB[cat]}")
                st.rerun()

    st.caption("Days with nothing spent need no entry — the Word file prints them as NIL.")
    if not tdf.empty:
        st.markdown("**Today's entries**")
        for r in tdf.itertuples():
            st.write(f"{inr(r.amount)} — {r.note} · _{LAB.get(r.cat, r.cat)}_")

# ---- DAY BOOK ----
elif page == "📒 Day book":
    m = month_picker("db_m")
    mdf = df[df.month == m].copy() if not df.empty else df
    st.caption("Edit any cell, or select rows and press Delete on your keyboard (bin icon on phone), then Save changes.")
    view = mdf[["id", "d", "amount", "cat", "note", "fixed"]].copy() if not mdf.empty else pd.DataFrame(columns=["id", "d", "amount", "cat", "note", "fixed"])
    view["d"] = pd.to_datetime(view["d"]).dt.date
    view = view.sort_values(["d", "id"], ascending=[False, True])
    ed = st.data_editor(
        view, hide_index=True, width="stretch", num_rows="dynamic", key=f"dbed_{m}",
        column_order=["d", "amount", "cat", "note", "fixed"],
        column_config={
            "d": st.column_config.DateColumn("Date", format="DD/MM/YYYY", required=True),
            "amount": st.column_config.NumberColumn("Amount ₹", step=1, required=True),
            "cat": st.column_config.SelectboxColumn("Head", options=cat_keys, required=True),
            "note": st.column_config.TextColumn("What for"),
            "fixed": st.column_config.CheckboxColumn("Monthly"),
        })
    st.caption("Head codes: " + " · ".join(f"**{k}** {v}" for k, v in LAB.items()))
    if st.button("Save changes", type="primary"):
        before = {int(r.id): r for r in view.itertuples()}
        kept = set()
        n_up = n_add = 0
        for r in ed.itertuples():
            if pd.isna(r.d) or pd.isna(r.amount):
                continue
            dv = r.d if isinstance(r.d, date) else pd.to_datetime(r.d).date()
            vals = (dv.isoformat(), int(r.amount), r.cat or "other", r.note if isinstance(r.note, str) else "", bool(r.fixed) if not pd.isna(r.fixed) else False)
            if not pd.isna(r.id) and int(r.id) in before:
                kept.add(int(r.id))
                b = before[int(r.id)]
                if (b.d.isoformat(), int(b.amount), b.cat, b.note, bool(b.fixed)) != vals:
                    run("UPDATE expenses SET d=%s, amount=%s, cat=%s, note=%s, fixed=%s WHERE id=%s", vals + (int(r.id),))
                    n_up += 1
            else:
                run("INSERT INTO expenses (d, amount, cat, note, fixed, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
                    vals + (datetime.now().isoformat(timespec="seconds"),))
                n_add += 1
        gone = [i for i in before if i not in kept]
        for i in gone:
            run("DELETE FROM expenses WHERE id=%s", (i,))
        st.toast(f"Saved: {n_up} changed, {n_add} added, {len(gone)} deleted")
        st.rerun()

    if not mdf.empty:
        st.subheader(f"{mlabel(m)} by day")
        for dday, g in sorted(mdf.groupby(mdf.d.dt.date), reverse=True):
            st.markdown(f'<div class="dayhead"><span>{dday:%a, %d %b}</span><span>{inr(g[g.cat.isin(CK)].amount.sum())}</span></div>', unsafe_allow_html=True)
            for r in g.itertuples():
                strike = "~~" if r.cat not in CK else ""
                st.markdown(f"{strike}{inr(r.amount)}{strike} &nbsp; {r.note} · <small>{LAB.get(r.cat, r.cat)}{' · monthly' if r.fixed else ''}</small>", unsafe_allow_html=True)

# ---- REPORTS ----
elif page == "📊 Reports":
    if df.empty:
        st.info("No expenses yet.")
        st.stop()
    tab1, tab2, tab3 = st.tabs(["This month", "Month by month", "Custom report"])
    with tab1:
        m = month_picker("rp_m")
        mdf = df[df.month == m]
        y_, mm_ = map(int, m.split("-"))
        pm = f"{y_ - 1}-12" if mm_ == 1 else f"{y_}-{mm_ - 1:02d}"
        pdf = df[df.month == pm]
        spent = mdf[mdf.cat.isin(CK)].amount.sum()
        pspent = pdf[pdf.cat.isin(CK)].amount.sum()
        edu = mdf[mdf.cat == "edu"].amount.sum()
        emi = mdf[mdf.cat == "emi"].amount.sum()
        hh = mdf[mdf.cat == "home"].amount.sum()
        phh = pdf[pdf.cat == "home"].amount.sum()
        pct = lambda v: f"{v / spent * 100:.0f}% of spend" if spent else ""
        kpis([("Total spent", inr(spent), (f"{'+' if spent >= pspent else '−'}{inr(abs(spent - pspent))} vs {mlabel(pm)}" if pspent else "")),
              ("Children's education", inr(edu), pct(edu)),
              ("Household expenses", inr(hh), pct(hh) + (f" · {mlabel(pm)[:3]} {inr(phh)}" if phh else "")),
              ("Loans & EMIs", inr(emi), pct(emi)),
              ("Everything else", inr(spent - edu - emi - hh), ""),
              ("Card bills (not counted)", inr(mdf[~mdf.cat.isin(CK)].amount.sum()), "")])
        g = mdf[mdf.cat.isin(CK)].groupby("cat").amount.sum().sort_values(ascending=False)
        if not g.empty:
            tbl = pd.DataFrame({"Head": [LAB.get(k, k) for k in g.index], "Amount ₹": g.values,
                                "Share": (g.values / spent * 100).round(1),
                                f"{mlabel(pm)} ₹": [int(pdf[pdf.cat == k].amount.sum()) for k in g.index]})
            c1, c2 = st.columns([1, 1]) if not IS_MOBILE else (st.container(), st.container())
            c1.dataframe(tbl, hide_index=True, width="stretch",
                         column_config={"Share": st.column_config.ProgressColumn("Share %", min_value=0, max_value=100, format="%.1f%%")})
            c2.bar_chart(tbl.set_index("Head")["Amount ₹"], horizontal=True)
            st.markdown("**Largest expenses**")
            big = mdf[mdf.cat.isin(CK)].nlargest(10, "amount")
            st.dataframe(pd.DataFrame({"Date": big.d.dt.strftime("%d %b"), "What for": big.note,
                                       "Head": big.cat.map(LAB), "Amount ₹": big.amount}), hide_index=True, width="stretch")
    with tab2:
        c = df[df.cat.isin(CK)]
        piv = c.pivot_table(index="cat", columns="month", values="amount", aggfunc="sum", fill_value=0)
        piv = piv.reindex([k for k in cats.key if k in piv.index])
        piv["Monthly avg"] = piv.mean(axis=1).round(0)
        total_row = piv.sum().to_frame().T
        total_row.index = ["total"]
        piv = pd.concat([total_row, piv])          # total spent sits on top, just under the month names
        piv.index = [LAB.get(k, "Total spent") for k in piv.index]
        piv.columns = [mlabel(x) if x != "Monthly avg" else x for x in piv.columns]
        styled = (piv.astype(int).style
                  .format(lambda v: inr(v)[1:])
                  .apply(lambda r: ["font-weight: bold; background-color: rgba(128,128,128,.12)" if r.name == "Total spent" else "" for _ in r], axis=1))
        st.dataframe(styled, width="stretch")
        chart = c.pivot_table(index="month", columns="cat", values="amount", aggfunc="sum", fill_value=0)
        chart.columns = [LAB.get(k, k) for k in chart.columns]
        chart.index = [mlabel(i) for i in chart.index]
        st.bar_chart(chart)
        st.download_button("⬇ Excel workbook (summary + one tab per month)", build_excel(df, cats),
                           file_name=f"expenses_{today:%Y%m%d}.xlsx", width="stretch" if IS_MOBILE else "content")
    with tab3:
        st.caption("Pick any dates, heads and words — e.g. all of Mithai's expenses this year, or medical since April.")
        c1, c2 = st.columns(2)
        d1 = c1.date_input("From", value=df.d.min().date(), format="DD/MM/YYYY", key="cr_from")
        d2 = c2.date_input("To", value=max(df.d.max().date(), today), format="DD/MM/YYYY", key="cr_to")
        heads = st.multiselect("Heads", cat_keys, default=[k for k in cat_keys if k in CK], format_func=lambda k: LAB[k])
        words = st.text_input("Contains words (optional, comma-separated, any match)", placeholder="e.g. Mithai, Mithi")
        rep = df[(df.d.dt.date >= d1) & (df.d.dt.date <= d2) & df.cat.isin(heads)]
        if words.strip():
            pats = [w.strip() for w in words.split(",") if w.strip()]
            rep = rep[rep.note.str.contains("|".join(map(re.escape, pats)), case=False, na=False)]
        nmon = max(1, (d2.year - d1.year) * 12 + d2.month - d1.month + 1)
        kpis([("Total", inr(rep.amount.sum()), f"{len(rep)} entries"),
              ("Per month", inr(rep.amount.sum() / nmon), f"over {nmon} month{'s' if nmon > 1 else ''}"),
              ("Largest", inr(rep.amount.max() if not rep.empty else 0), (rep.loc[rep.amount.idxmax(), 'note'] if not rep.empty else ""))])
        if not rep.empty:
            by = rep.groupby(["month", "cat"]).amount.sum().unstack(fill_value=0)
            by.columns = [LAB.get(k, k) for k in by.columns]
            by["Total"] = by.sum(axis=1)
            by.index = [mlabel(i) for i in by.index]
            st.dataframe(by, width="stretch")
            st.dataframe(pd.DataFrame({"Date": rep.d.dt.strftime("%d-%m-%Y"), "Head": rep.cat.map(LAB), "What for": rep.note, "Amount ₹": rep.amount}),
                         hide_index=True, width="stretch")
            title = "Expense report" + (f" — {words}" if words.strip() else "")
            sub = f"{d1:%d %b %Y} to {d2:%d %b %Y} · {', '.join(LAB[k] for k in heads)} · total {inr(rep.amount.sum())}"
            b1, b2 = st.columns(2)
            b1.download_button("⬇ Word report", build_report_word(title, sub, rep, cats), file_name="expense_report.docx", width="stretch")
            b2.download_button("⬇ CSV for Excel", ("﻿" + rep.assign(d=rep.d.dt.strftime("%d-%m-%Y"), cat=rep.cat.map(LAB))[["d", "cat", "note", "amount"]]
                               .rename(columns={"d": "Date", "cat": "Head", "note": "What for", "amount": "Amount"}).to_csv(index=False)).encode("utf-8"),
                               file_name="expense_report.csv", width="stretch")

# ---- WORD FILE ----
elif page == "📄 Word file":
    st.caption("Your monthly log in the same day-wise style as before (NIL on empty days, card bills in brackets), with a summary by head at the end.")
    m = month_picker("wf_m")
    if df.empty or df[df.month == m].empty:
        st.info(f"No entries for {mlabel(m)} yet.")
    else:
        data = build_word(m, df, cats)
        st.download_button(f"⬇ Download {mlabel(m)}.docx", data, file_name=f"{MONTHS[int(m[5:]) - 1]}_{m[:4]}.docx",
                           type="primary", width="stretch")
        mdf = df[df.month == m]
        y, mm = map(int, m.split("-"))
        with st.expander("Preview", expanded=True):
            lines = []
            for day in range(1, calendar.monthrange(y, mm)[1] + 1):
                dd = mdf[mdf.d.dt.day == day]
                txt = "NIL" if dd.empty else " ".join((f"{x.note} {x.amount}/-" if x.cat in CK else f"({x.note} {x.amount}/-)") for x in dd.itertuples())
                lines.append(f"**{day}/{mm}/{str(y)[2:]}** - {txt}")
            st.markdown("  \n".join(lines))

# ---- SETTINGS ----
elif page == "⚙️ Settings":
    st.subheader("Heads (categories)")
    st.caption("Rename heads, add new ones (give a short code), or untick ‘Counted’ to keep entries on record but out of totals.")
    ce = st.data_editor(cats[["key", "label", "counted"]], hide_index=True, num_rows="dynamic", width="stretch",
                        column_config={"key": st.column_config.TextColumn("Code", required=True),
                                       "label": st.column_config.TextColumn("Head name", required=True),
                                       "counted": st.column_config.CheckboxColumn("Counted")})
    if st.button("Save heads", type="primary"):
        used = set(df.cat) if not df.empty else set()
        new_keys = set(ce.key.dropna())
        missing = used - new_keys
        if missing:
            st.error("These codes still have entries, so they can't be removed: " + ", ".join(sorted(missing)))
        else:
            run("DELETE FROM categories")
            run("INSERT INTO categories (key, label, counted, sort) VALUES (%s,%s,%s,%s)",
                [(r.key.strip(), r.label.strip(), bool(r.counted), i) for i, r in enumerate(ce.dropna(subset=["key", "label"]).itertuples())], many=True)
            st.toast("Heads saved")
            st.rerun()
    st.divider()
    st.subheader("Backup")
    st.download_button("⬇ Full Excel backup", build_excel(df, cats), file_name=f"expense_backup_{today:%Y%m%d}.xlsx")
    st.caption(f"Storage: {'Postgres (online)' if DATABASE_URL else 'local file ' + SQLITE_FILE + ' — set DATABASE_URL on Render so data survives redeploys'}.")
