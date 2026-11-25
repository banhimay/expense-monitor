"""💰 Assets tab — monthly net-worth tracker (moved in from the Asset Monitor artifact).

Data: table asset_months(month 'YYYY-MM', as_on date, items JSON text). Each item is
{"cat", "name", "value", ...extras} where extras depend on the category:
  mf: invested, sip, plan, rta, since      demat: holdings, cash (value = holdings + cash)
  ins: cover, premium, due, note           loan: principal, start   (loan value = outstanding)
"""
import json
from datetime import date, datetime
from io import BytesIO

import pandas as pd
import streamlit as st

CATS = [  # key, label, group
    ("cash", "Cash in hand", "liquid"), ("bank", "Bank savings", "liquid"), ("fd", "Fixed deposits", "liquid"),
    ("demat", "Demat (stocks)", "demat"), ("mf", "Mutual funds", "mf"),
    ("ins", "Life insurance (surrender value)", "ins"), ("nps", "NPS", "retire"), ("pf", "GPF & PPF", "pf"),
    ("gold", "Gold", "gold"), ("coop", "Co-operative society", "coop"), ("apy", "Atal Pension Yojana", "retire"),
    ("loan", "Loans", "loan"),
]
CAT = {k: (l, g) for k, l, g in CATS}
GROUPS = [("gold", "Gold"), ("pf", "GPF & PPF"), ("mf", "Mutual funds"), ("demat", "Stocks"),
          ("liquid", "Bank & cash"), ("ins", "Insurance"), ("retire", "NPS & APY"), ("coop", "Co-operative")]
EXTRA = {  # extra editable fields per category: (key, label, kind)
    "mf": [("invested", "Invested ₹", "num"), ("sip", "SIP / month ₹", "num"), ("plan", "Plan / note", "text"),
           ("rta", "RTA", "text"), ("since", "Since (YYYY-MM-DD)", "text")],
    "demat": [("holdings", "Holdings ₹", "num"), ("cash", "Cash ₹", "num")],
    "ins": [("premium", "Annual premium ₹", "num"), ("cover", "Cover", "text"), ("due", "Premium month", "text"),
            ("note", "Note", "text")],
    "loan": [("principal", "Loan amount ₹", "num"), ("start", "Started", "text"), ("note", "Note", "text")],
}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def short(n):
    a = abs(n); s = "−" if n < 0 else ""
    if a >= 1e7: return f"{s}₹{a / 1e7:.2f} Cr"
    if a >= 1e5: return f"{s}₹{a / 1e5:.2f} L"
    return f"{s}₹{a:,.0f}"


def signed(n, inr):
    return ("+" if n > 0 else "−" if n < 0 else "±") + inr(abs(n))


def ind(v):
    """Indian digit grouping without the ₹ sign; blank for empty cells."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "–"
    n = int(round(v)); s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head: parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("−" if n < 0 else "") + s


def show(df, money=(), pct=(), bold_row=None, height=None):
    df = df.copy()
    money = [c for c in money if c in df]; pct = [c for c in pct if c in df]
    for c in money:
        df[c] = df[c].map(ind)
    for c in pct:
        df[c] = df[c].map(lambda v: "–" if v is None or pd.isna(v) else f"{v:.1f}%")
    sty = df.style.set_properties(subset=money + pct, **{"text-align": "right"})
    if bold_row is not None:
        sty = sty.apply(lambda r: ["font-weight: bold" if r.name == bold_row else "" for _ in r], axis=1)
    kw = {"height": height} if height else {}
    st.dataframe(sty, hide_index=bold_row is None, width="stretch", **kw)


def next_month(m):
    y, mm = map(int, m.split("-"))
    return f"{y + 1}-01" if mm == 12 else f"{y}-{mm + 1:02d}"


def totals(items):
    t = {"assets": 0, "loans": 0, "cat": {}, "grp": {}, "mf_inv": 0, "mf_val": 0, "sip": 0}
    for i in items:
        v = int(i.get("value") or 0)
        t["cat"][i["cat"]] = t["cat"].get(i["cat"], 0) + v
        if i["cat"] == "loan":
            t["loans"] += v
        else:
            t["assets"] += v
            g = CAT.get(i["cat"], ("", "liquid"))[1]
            t["grp"][g] = t["grp"].get(g, 0) + v
        if i["cat"] == "mf":
            t["mf_inv"] += int(i.get("invested") or 0); t["mf_val"] += v; t["sip"] += int(i.get("sip") or 0)
    t["net"] = t["assets"] - t["loans"]
    return t


def load(run):
    rows = run("SELECT month, as_on, items FROM asset_months ORDER BY month", fetch=True)
    out = {}
    for m, on, items in rows:
        on = on if isinstance(on, date) else datetime.strptime(str(on)[:10], "%Y-%m-%d").date()
        out[m] = {"month": m, "asOn": on, "items": json.loads(items)}
    return out


def save(run, m, as_on, items):
    run("DELETE FROM asset_months WHERE month=%s", (m,))
    run("INSERT INTO asset_months (month, as_on, items, updated_at) VALUES (%s,%s,%s,%s)",
        (m, as_on.isoformat(), json.dumps(items, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")))


def render(run, inr, kpis, mlabel, IS_MOBILE):
    data = load(run)
    months = sorted(data)
    if not months:
        st.info("No asset months yet.")
        if st.button(f"Start {mlabel(date.today().strftime('%Y-%m'))}", type="primary"):
            save(run, date.today().strftime("%Y-%m"), date.today().replace(day=1), [])
            st.rerun()
        return

    opts = months[::-1]
    if "as_month_pending" in st.session_state:          # set by "Start next month" before the selector exists
        st.session_state["as_month"] = st.session_state.pop("as_month_pending")
    m = st.selectbox("Month", opts, format_func=mlabel, key="as_month")
    doc = data[m]
    i = months.index(m)
    prev = data[months[i - 1]] if i > 0 else None
    t, pt = totals(doc["items"]), (totals(prev["items"]) if prev else None)
    prev_by = {x["name"]: x for x in (prev["items"] if prev else [])}

    ch = t["net"] - pt["net"] if pt else None
    kpis([(f"Net worth · as on {doc['asOn']:%d %b %Y}", short(t["net"]), inr(t["net"]) + (
              f" · {signed(ch, inr)} vs {MONTHS[int(prev['month'][5:]) - 1][:3]}" if pt else "")),
          ("Total assets", short(t["assets"]), signed(t["assets"] - pt["assets"], inr) if pt else ""),
          ("Loans outstanding", short(t["loans"]), signed(t["loans"] - pt["loans"], inr) if pt else ""),
          ("Debt to assets", f"{t['loans'] / t['assets'] * 100:.1f}%" if t["assets"] else "–", "")])

    tab1, tab2, tab3, tab4 = st.tabs(["Overview", "Monthly update", "History", "Mutual funds"])

    # ---------- Overview ----------
    with tab1:
        segs = [(lbl, t["grp"].get(g, 0)) for g, lbl in GROUPS if t["grp"].get(g, 0) > 0]
        alloc = pd.DataFrame({"Where the money sits": [s[0] for s in segs], "Amount ₹": [s[1] for s in segs],
                              "Share %": [round(s[1] / t["assets"] * 100, 1) for s in segs]}).sort_values("Amount ₹", ascending=False)
        show(alloc, money=["Amount ₹"], pct=["Share %"])

        st.markdown(f"**Assets and loans by category** · {'change vs ' + mlabel(prev['month']) if prev else 'first recorded month'}")
        for k, lbl, _ in CATS:
            its = [x for x in doc["items"] if x["cat"] == k]
            if not its:
                continue
            v = t["cat"].get(k, 0); pv = pt["cat"].get(k, 0) if pt else None
            d = f" · {signed(v - pv, inr)}" if pv is not None else ""
            with st.expander(f"{lbl} ({len(its)}) — {inr(v)}{d}"):
                rows = []
                for x in sorted(its, key=lambda x: -int(x.get("value") or 0)):
                    p = prev_by.get(x["name"])
                    extra = []
                    if k == "ins" and x.get("cover"): extra.append("cover " + str(x["cover"]))
                    if k == "demat" and x.get("cash"): extra.append(f"incl. {inr(x['cash'])} cash")
                    rows.append({"Item": x["name"] + (f" · {', '.join(extra)}" if extra else ""),
                                 "Value ₹": int(x.get("value") or 0),
                                 "Change ₹": (int(x.get("value") or 0) - int(p.get("value") or 0)) if p else None})
                show(pd.DataFrame(rows), money=["Value ₹", "Change ₹"])

        if prev:
            moves = []
            for x in doc["items"]:
                p = prev_by.get(x["name"]); dv = int(x.get("value") or 0) - (int(p.get("value") or 0) if p else 0)
                if dv:
                    moves.append({"Item": x["name"] + ("" if p else " (new)"), "Category": CAT.get(x["cat"], (x["cat"],))[0],
                                  "Now ₹": int(x.get("value") or 0), "Change ₹": dv})
            if moves:
                st.markdown(f"**Biggest moves since {mlabel(prev['month'])}**")
                mv = pd.DataFrame(moves); mv = mv.reindex(mv["Change ₹"].abs().sort_values(ascending=False).index).head(8)
                show(mv, money=["Now ₹", "Change ₹"])

    # ---------- Monthly update ----------
    with tab2:
        latest = months[-1]
        nm = next_month(latest)
        if m == latest:
            with st.container(border=True):
                st.markdown(f"**Starting a new month?** {mlabel(nm)} will start as a copy of {mlabel(latest)}, "
                            f"so you change only what moved.")
                if st.button(f"Start {mlabel(nm)}", type="primary"):
                    y, mm = map(int, nm.split("-"))
                    save(run, nm, date(y, mm, 1), json.loads(json.dumps(data[latest]["items"])))
                    st.session_state["as_month_pending"] = nm
                    st.toast(f"{mlabel(nm)} started from {mlabel(latest)}")
                    st.rerun()

        st.markdown(f"#### Edit {mlabel(m)}")
        as_on = st.date_input("Balance as on", value=doc["asOn"], format="DD/MM/YYYY", key=f"ason_{m}")
        st.caption("Edit any amount, add a row at the bottom of a table, or select rows and delete them. "
                   "Demat value is worked out as holdings + cash. Then press **Save** below.")
        edited = {}
        for k, lbl, _ in CATS:
            its = [x for x in doc["items"] if x["cat"] == k]
            extra = EXTRA.get(k, [])
            cols = ["name"] + ([] if k == "demat" else ["value"]) + [e[0] for e in extra]
            df = pd.DataFrame([{c: x.get(c) for c in cols} for x in its], columns=cols)
            for e in extra:
                if e[2] == "num": df[e[0]] = pd.to_numeric(df[e[0]], errors="coerce")
            if "value" in df: df["value"] = pd.to_numeric(df["value"], errors="coerce")
            cfg = {"name": st.column_config.TextColumn("Name", required=True, width="large"),
                   "value": st.column_config.NumberColumn("Outstanding ₹" if k == "loan" else (
                       "Surrender value ₹" if k == "ins" else "Value ₹"), step=1, format="%d")}
            for key_, lab, kind in extra:
                cfg[key_] = (st.column_config.NumberColumn(lab, step=1, format="%d") if kind == "num"
                             else st.column_config.TextColumn(lab))
            total = sum(int(x.get("value") or 0) for x in its)
            with st.expander(f"{lbl} — {inr(total)}", expanded=False):
                edited[k] = st.data_editor(df, hide_index=True, num_rows="dynamic", width="stretch",
                                           column_config=cfg, key=f"ed_{m}_{k}")

        c1, c2 = st.columns([1, 1])
        if c1.button(f"💾 Save {mlabel(m)}", type="primary", width="stretch"):
            items = []
            for k, lbl, _ in CATS:
                for r in edited[k].to_dict("records"):
                    name = (r.get("name") or "").strip() if isinstance(r.get("name"), str) else ""
                    if not name:
                        continue
                    it = {"cat": k, "name": name}
                    for key_, _, kind in EXTRA.get(k, []):
                        v = r.get(key_)
                        if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
                            continue
                        it[key_] = int(v) if kind == "num" else str(v)
                    if k == "demat":
                        it["value"] = int(it.get("holdings", 0)) + int(it.get("cash", 0))
                    else:
                        v = r.get("value")
                        it["value"] = 0 if v is None or (isinstance(v, float) and pd.isna(v)) else int(v)
                    items.append(it)
            save(run, m, as_on, items)
            nt = totals(items)
            st.toast(f"Saved {mlabel(m)} · net worth {inr(nt['net'])}")
            st.rerun()
        with c2.popover(f"🗑 Delete {mlabel(m)}", width="stretch"):
            st.write(f"Delete **{mlabel(m)}** for good? Other months stay as they are.")
            if st.button("Yes, delete this month", key=f"del_{m}"):
                run("DELETE FROM asset_months WHERE month=%s", (m,))
                st.session_state.pop("as_month", None)
                st.rerun()

    # ---------- History ----------
    with tab3:
        rows = [{"Month": mlabel(mm), "_m": mm, **{k: v for k, v in totals(data[mm]["items"]).items() if k in ("assets", "loans", "net")}}
                for mm in months]
        h = pd.DataFrame(rows)
        first, last = h.iloc[0], h.iloc[-1]
        st.markdown(f"**Net worth by month** · {len(h)} months · {signed(last['net'] - first['net'], inr)} since {first['Month']}")
        chart = h.set_index("_m")[["net"]].rename(columns={"net": "Net worth ₹"})
        chart.index = pd.to_datetime([x + "-01" for x in chart.index])     # real dates keep months in order
        st.line_chart(chart)
        tbl = h[::-1].copy()
        tbl["Change ₹"] = tbl["net"] - tbl["net"].shift(-1)
        show(tbl.rename(columns={"assets": "Assets ₹", "loans": "Loans ₹", "net": "Net worth ₹"})[
                 ["Month", "Assets ₹", "Loans ₹", "Net worth ₹", "Change ₹"]],
             money=["Assets ₹", "Loans ₹", "Net worth ₹", "Change ₹"])
        st.markdown("**Category totals by month** (newest first)")
        used = [k for k, _, _ in CATS if any(x["cat"] == k for mm in months for x in data[mm]["items"])]
        ct = pd.DataFrame({mlabel(mm): [totals(data[mm]["items"])["cat"].get(k, 0) for k in used] + [totals(data[mm]["items"])["net"]]
                           for mm in months[::-1]}, index=[CAT[k][0] for k in used] + ["Net worth"])
        show(ct, money=list(ct.columns), bold_row="Net worth", height=(len(ct) + 1) * 35 + 3)
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as xw:
            ct.to_excel(xw, sheet_name="Summary")
            for mm in months[::-1]:
                pd.DataFrame([{"Category": CAT.get(x["cat"], (x["cat"],))[0], **{k: v for k, v in x.items() if k != "cat"}}
                              for x in data[mm]["items"]]).to_excel(xw, sheet_name=mlabel(mm)[:31], index=False)
        st.download_button("⬇ Excel workbook (summary + one tab per month)", buf.getvalue(),
                           file_name=f"assets_{date.today():%Y%m%d}.xlsx")

    # ---------- Mutual funds ----------
    with tab4:
        funds = sorted([x for x in doc["items"] if x["cat"] == "mf"], key=lambda x: -int(x.get("value") or 0))
        gain = t["mf_val"] - t["mf_inv"]
        kpis([("Invested", short(t["mf_inv"]), ""), ("Current value", short(t["mf_val"]), ""),
              ("Gain", short(gain), f"{gain / t['mf_inv'] * 100:.1f}% absolute" if t["mf_inv"] else ""),
              ("Monthly SIP", inr(t["sip"]), f"{sum(1 for f in funds if int(f.get('sip') or 0) > 0)} active SIPs")])
        fdf = pd.DataFrame([{
            "Fund": f["name"], "Plan": f.get("plan", ""), "Invested ₹": int(f.get("invested") or 0),
            "Value ₹": int(f.get("value") or 0), "Gain ₹": int(f.get("value") or 0) - int(f.get("invested") or 0),
            "Return %": round((int(f.get("value") or 0) - int(f.get("invested") or 0)) / int(f["invested"]) * 100, 1) if f.get("invested") else None,
            "SIP ₹": int(f.get("sip") or 0) or None, "Since": f.get("since", ""), "RTA": f.get("rta", "")} for f in funds])
        st.markdown(f"**Funds as on {doc['asOn']:%d %b %Y}** · {len(funds)} holdings")
        show(fdf, money=["Invested ₹", "Value ₹", "Gain ₹", "SIP ₹"], pct=["Return %"], height=(len(fdf) + 1) * 35 + 3)
