from __future__ import annotations
import sys
import importlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from src.calculations import annual_growth_by_period, pat_margin, debt_to_equity, implied_pe
import src.data_loader as data_loader
data_loader = importlib.reload(data_loader)
DATA_DIR = data_loader.DATA_DIR
DataValidationError = data_loader.DataValidationError
append_provenance = data_loader.append_provenance
load_dataset = data_loader.load_dataset
load_provenance = data_loader.load_provenance
parse_uploaded_csv = data_loader.parse_uploaded_csv
save_dataset = data_loader.save_dataset
validate_dataframe = data_loader.validate_dataframe
REQUIRED_COLUMNS = data_loader.REQUIRED_COLUMNS
append_import_only = data_loader.append_import_only
from src.research import data_quality_summary, data_status_label, financial_period_warnings
from src.scenario import calculate_scenario, scenario_comparison, sensitivity_table
from src.retrieval import NseIpoAdapter
from src.retrieval.base import RetrievalResult
from src.retrieval.nse import NseRetrievalError
from src.retrieval.storage import append_retrieval, load_retrieval_history
from datetime import datetime, timezone
from urllib.parse import urlencode

st.set_page_config(page_title="IPO Scenario Simulator & Research", page_icon="📈", layout="wide")
st.markdown("""
<style>
  .stApp { background: #f5f7fb; }
  [data-testid="stHeader"] { background: rgba(245,247,251,.85); }
  [data-testid="stSidebar"] { background: #101d32; }
  [data-testid="stSidebar"] * { color: #e7edf7; }
  [data-testid="stSidebar"] [data-baseweb="select"] * { color: #162238; }
  h1, h2, h3 { color: #14233a; letter-spacing: -.025em; }
  [data-testid="stMetric"] { background: white; border: 1px solid #e2e8f0; padding: 16px 18px; border-radius: 14px; box-shadow: 0 3px 14px rgba(17,35,58,.045); }
  [data-testid="stMetricLabel"] { color: #64748b; }
  [data-testid="stExpander"] { background: white; border: 1px solid #e2e8f0; border-radius: 12px; }
  [data-testid="stDataFrame"] { border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; }
  @media (max-width: 720px) { .block-container { padding: 1rem .75rem 2rem; } [data-testid="stMetric"] { padding: 12px; } }
</style>
""", unsafe_allow_html=True)
st.title("📈 IPO Scenario Simulator & Research")
st.caption("Research workspace for Indian Mainboard and SME IPOs. All values are user supplied or explicitly labeled demonstration data.")

@st.cache_data(show_spinner=False)
def read_all():
    return {name: load_dataset(name) for name in ("ipo_master", "financials", "subscription", "peers")}

if "datasets" not in st.session_state:
    try:
        st.session_state.datasets = read_all()
    except DataValidationError as exc:
        st.error(f"Stored data could not be loaded: {exc}")
        st.session_state.datasets = {name: pd.DataFrame() for name in ("ipo_master", "financials", "subscription", "peers")}
data = st.session_state.datasets
pages = ["Dashboard", "IPO Research", "Financial Analysis", "Scenario Simulator", "Data Management", "Methodology"]
page = st.sidebar.radio("Pages", pages)
st.sidebar.caption("Offline-first by default · source refreshes are manual and user initiated.")

master, financials, subscriptions, peers = (data[n] for n in ("ipo_master", "financials", "subscription", "peers"))
segment_options = [segment for segment in ["Mainboard", "SME"] if not master.empty and master.segment.astype(str).eq(segment).any()]
selected_segments = st.sidebar.multiselect("Segment filter", segment_options, default=segment_options, key="global_segment_filter")
dashboard_master = master[master.segment.astype(str).isin(selected_segments)].copy() if not master.empty else master.copy()
if not master.empty:
    active_ids = master.ipo_id.astype(str).tolist()
    # Forms must not mutate the value of an already-instantiated selectbox.
    # Apply a pending selection before creating the widget on the rerun.
    pending_active = st.session_state.pop("pending_active_ipo_id", None)
    if pending_active in active_ids:
        st.session_state.active_ipo_id = pending_active
    if st.session_state.get("active_ipo_id") not in active_ids:
        st.session_state.active_ipo_id = active_ids[0]
    st.sidebar.selectbox("Active IPO", active_ids,
                         format_func=lambda value: master.loc[master.ipo_id.astype(str).eq(value), "company_name"].iloc[0],
                         key="active_ipo_id", help="Shared selection for research, financials, subscription and scenarios.")

def persist_dataset(name: str, frame: pd.DataFrame, *, provenance: dict | None = None) -> None:
    """Validate, save to local CSV and refresh all app views immediately."""
    saved_path = save_dataset(name, frame)
    data[name] = load_dataset(name)
    st.session_state.datasets[name] = data[name]
    read_all.clear()
    st.session_state[f"saved_notice_{name}"] = f"Saved locally to {saved_path.name}; changes are available after refresh and app restart."
    if provenance:
        append_provenance(name, provenance.get("record_key", ""), action=provenance.get("action", "save"),
                          source_url=provenance.get("source_url", ""), observation_date=provenance.get("observation_date", ""),
                          reporting_period=provenance.get("reporting_period", ""), data_status=provenance.get("data_status", "MANUAL"))

def row_data_label(status):
    return data_status_label(status)

def source_freshness(source_date):
    if source_date is None or pd.isna(source_date) or not str(source_date).strip():
        return "NO SOURCE DATE"
    parsed = pd.to_datetime(source_date, errors="coerce", utc=True)
    if pd.isna(parsed):
        return "DATE UNAVAILABLE"
    return "STALE" if pd.Timestamp.now(tz="UTC") - parsed > pd.Timedelta(days=90) else "CURRENT"

def display_value(value, unavailable="Unavailable"):
    return unavailable if value is None or pd.isna(value) or not str(value).strip() else value

def input_text(value):
    return "" if value is None or pd.isna(value) else str(value)

if page == "Dashboard":
    st.subheader("Dashboard")
    quality = data_quality_summary(*data.values())
    c1, c2, c3 = st.columns(3)
    core = ["company_name", "segment", "status", "open_date", "close_date", "price_band_low", "price_band_high", "lot_size", "issue_size_crore", "source_url", "source_date"]
    if dashboard_master.empty:
        completeness = 0.0
    else:
        present = dashboard_master[core].notna() & dashboard_master[core].astype(str).apply(lambda col: col.str.strip().ne(""))
        completeness = float(present.sum().sum() / (len(dashboard_master) * len(core)) * 100)
    c1.metric("Available IPOs", len(dashboard_master), help="IPO records included by the sidebar segment filter.")
    c2.metric("Listed IPOs", int(dashboard_master.status.eq("Listed").sum()) if "status" in dashboard_master else 0)
    c3.metric("Data completeness", f"{completeness:.0f}%", help="Share of populated cells across company, segment, status, dates, price band, lot size, issue size and source fields.")
    if quality["demonstration_rows"]:
        st.warning(f"{quality['demonstration_rows']} rows are marked DEMONSTRATION ONLY. These synthetic records are not real IPO data.")
    st.markdown("#### IPO coverage")
    visible_master = dashboard_master.copy()
    if master.empty:
        st.info("No IPO records yet. Add one in Data Management.")
    elif dashboard_master.empty:
        st.info("No IPOs match the selected segment filter. Choose Mainboard or SME in the sidebar.")
    else:
        search = st.text_input("Search IPOs", placeholder="Search company, IPO ID, sector or status", key="dashboard_search")
        if search.strip():
            terms = search.strip().casefold()
            text_columns = [c for c in ["ipo_id", "company_name", "sector", "status", "exchange"] if c in visible_master]
            found = pd.Series(False, index=visible_master.index)
            for col in text_columns:
                found |= visible_master[col].astype(str).str.casefold().str.contains(terms, na=False)
            visible_master = visible_master[found]
        if visible_master.empty:
            st.info("No IPO records match that search. Try a company name, sector, IPO ID or status.")
        else:
            visible_master["Data label"] = visible_master.data_status.map(row_data_label)
            visible_master["Freshness"] = visible_master.source_date.map(source_freshness)
            st.dataframe(visible_master, use_container_width=True, hide_index=True)
            st.download_button("Download filtered IPO CSV", visible_master.drop(columns=["Data label", "Freshness"]).to_csv(index=False).encode("utf-8"), file_name="ipo_research_filtered.csv", mime="text/csv")
        chart = dashboard_master.copy()
        chart["issue_size_crore"] = pd.to_numeric(chart.issue_size_crore, errors="coerce")
        chart = chart[chart.issue_size_crore.notna()]
        if not chart.empty:
            st.plotly_chart(px.bar(chart, x="company_name", y="issue_size_crore", color="segment", hover_data=["data_status", "source_date"], title="Supplied issue sizes (INR crore)"), use_container_width=True)
        else:
            st.info("No issue-size figures are available for a chart. Missing amounts are not drawn as zero.")
    visible_ids = set(visible_master.ipo_id.astype(str)) if not visible_master.empty else set()
    if not financials.empty:
        financial_chart = financials[financials.ipo_id.astype(str).isin(visible_ids)].copy()
        available_financials = [col for col in ["revenue_crore", "pat_crore"] if financial_chart[col].notna().any()]
        if available_financials:
            annual = financial_chart.groupby("financial_year", as_index=False)[available_financials].sum(min_count=1)
            st.plotly_chart(px.bar(annual, x="financial_year", y=available_financials, barmode="group", title="Supplied financial totals by reporting year (INR crore)"), use_container_width=True)
            st.caption("Totals combine supplied IPO records for each displayed year; they are not forecasts and do not fill missing years.")
        st.download_button("Download financial records CSV", financial_chart.to_csv(index=False).encode("utf-8"), file_name="financial_records.csv", mime="text/csv")
    if not subscriptions.empty:
        shown_subs = subscriptions[subscriptions.ipo_id.astype(str).isin(dashboard_master.ipo_id.astype(str))] if not dashboard_master.empty else subscriptions.iloc[0:0]
        if not shown_subs.empty and pd.to_numeric(shown_subs.subscription_multiple, errors="coerce").notna().any():
            st.plotly_chart(px.bar(shown_subs, x="category", y="subscription_multiple", color="ipo_id", hover_data=[c for c in ["data_status", "as_of", "source_url"] if c in shown_subs], title="Supplied subscription multiples (DEMO rows are labeled)"), use_container_width=True)
    st.caption(f"Workspace rows: {quality['rows']} · Rows with source URL: {quality['rows_with_source']}. Missing source data is not inferred.")

elif page == "IPO Research":
    st.subheader("IPO Research")
    if dashboard_master.empty:
        st.info("Add IPO records from Data Management to begin research.")
    else:
        company_search = st.text_input("Find an IPO", placeholder="Type a company name or IPO ID")
        research_options = dashboard_master.copy()
        if company_search.strip():
            term = company_search.strip().casefold()
            matches = research_options.company_name.astype(str).str.casefold().str.contains(term, na=False) | research_options.ipo_id.astype(str).str.casefold().str.contains(term, na=False)
            research_options = research_options[matches]
        if research_options.empty:
            st.info("No IPO matches. Clear the search or adjust the segment filter in the sidebar.")
        else:
            choice = st.session_state.get("active_ipo_id")
            if choice not in set(research_options.ipo_id.astype(str)):
                choice = research_options.ipo_id.astype(str).iloc[0]
            st.caption("Selected IPO follows the shared Active IPO control in the sidebar.")
            row = research_options.loc[research_options.ipo_id.astype(str).eq(choice)].iloc[0]
            label = row_data_label(row.get("data_status"))
            freshness = source_freshness(row.get("source_date"))
            if label == "DEMO ONLY":
                st.warning("DEMO ONLY — this synthetic record does not describe an actual IPO or verified market data.")
            st.markdown(f"### {row.company_name}  ·  `{label}`  ·  `{freshness}`")
            st.write(f"**{row['segment']} · {row['exchange']} · {row['sector']}** — {row.get('status', '')}")
            with st.expander("Issue overview", expanded=True):
                a,b,c,d = st.columns(4)
                a.metric("Issue size (INR crore)", f"{row.issue_size_crore:,.2f}" if pd.notna(row.issue_size_crore) else "Unavailable")
                low = f"{row.price_band_low:g}" if pd.notna(row.price_band_low) else "Unavailable"
                high = f"{row.price_band_high:g}" if pd.notna(row.price_band_high) else "Unavailable"
                b.metric("Price band (₹)", f"{low}–{high}" if low != "Unavailable" or high != "Unavailable" else "Unavailable")
                c.metric("Lot size", f"{int(row.lot_size):,}" if pd.notna(row.lot_size) else "Unavailable")
                d.metric("Application at upper band (₹)", f"{row.price_band_high * row.lot_size:,.2f}" if pd.notna(row.price_band_high) and pd.notna(row.lot_size) else "Unavailable")
                listing = f"₹{row.listing_price:g}" if pd.notna(row.listing_price) else "Unavailable — no verified listing price"
                st.write(f"Open: {display_value(row.open_date)} · Close: {display_value(row.close_date)} · Listing date: {display_value(row.get('listing_date', ''))} · Listing price: {listing}")
            with st.expander("Source documents and provenance", expanded=True):
                source_date = row.get("source_date", "")
                source_date = source_date if pd.notna(source_date) and str(source_date).strip() else "Unavailable"
                st.write(f"Data label: **{label}** · Source/reporting date: **{source_date}** · Freshness: **{freshness}**")
                for label_text, field in (("Source", "source_url"), ("DRHP", "drhp_url"), ("RHP", "rhp_url")):
                    value = row.get(field, "")
                    if pd.notna(value) and str(value).strip(): st.markdown(f"[{label_text}: {value}]({value})")
                if not any(pd.notna(row.get(field)) and str(row.get(field)).strip() for field in ("source_url", "drhp_url", "rhp_url")):
                    st.caption("No source links supplied yet. Add a source through CSV import or manual entry.")
            with st.expander("Subscription data", expanded=False):
                s = subscriptions[subscriptions.ipo_id.astype(str).eq(choice)] if not subscriptions.empty else pd.DataFrame()
                if not s.empty:
                    st.dataframe(s.where(pd.notna(s), "Unavailable"), use_container_width=True, hide_index=True)
                    valid_subs = pd.to_numeric(s.subscription_multiple, errors="coerce").notna()
                    if valid_subs.any():
                        st.plotly_chart(px.bar(s.loc[valid_subs], x="category", y="subscription_multiple", title="Saved subscription multiples — source values"), use_container_width=True)
                    if "source_url" in s and s.source_url.notna().any(): st.caption("Source: " + "; ".join(sorted(set(s.source_url.dropna().astype(str)))))
                    else: st.caption("No source URL supplied.")
                    if "as_of" in s and s.as_of.notna().any(): st.caption("Observation dates: " + ", ".join(sorted(set(s.as_of.dropna().astype(str)))))
                    else: st.caption("Observation date unavailable.")
                else: st.caption("No subscription data entered. GMP and subscription are never estimated by this app.")
            with st.expander("Peer references", expanded=False):
                p = peers[peers.ipo_id.astype(str).eq(choice)] if not peers.empty else pd.DataFrame()
                st.dataframe(p, use_container_width=True, hide_index=True) if not p.empty else st.caption("No peer data entered.")

elif page == "Financial Analysis":
    st.subheader("Financial Analysis")
    active_ids = set(master.ipo_id.astype(str)) if not master.empty else set()
    selected = st.session_state.get("active_ipo_id")
    if selected not in active_ids:
        choices = sorted(active_ids or set(financials.ipo_id.astype(str))) if not financials.empty or active_ids else []
        selected = st.selectbox("IPO ID", choices, key="financial_ipo_fallback") if choices else None
    if selected:
        st.caption(f"Active IPO: {selected} · shared with the other pages.")
    f = financials[financials.ipo_id.astype(str).eq(str(selected))].copy() if selected and not financials.empty else pd.DataFrame(columns=financials.columns)
    if f.empty:
        st.info("No company financial statements are available for this IPO yet. Add sourced records manually or import a CSV in Data Management; missing figures are not estimated.")
    else:
        f["_period_order"] = pd.to_numeric(f.financial_year.astype(str).str.extract(r"(\d{4})")[0], errors="coerce")
        f = f.sort_values(["_period_order", "financial_year"], na_position="last").drop(columns="_period_order")
        st.warning("Unit check: revenue, EBITDA, PAT, borrowings and net worth must be INR crore; EPS and market price must be INR per share. Units cannot be inferred from numeric values, so verify each source before comparing periods.")
        if f.data_status.astype(str).str.upper().eq("DEMO").any(): st.warning("DEMO ONLY — these figures are illustrative and are not actual company financials.")
        for warning in financial_period_warnings(f): st.warning(warning)
        price_text = st.text_input("Market price for derived P/E (₹ per share, optional)", placeholder="Leave blank if unavailable", help="Enter a verified price for analysis. This offline app does not fetch or estimate market prices.")
        market_price = np.nan
        if price_text.strip():
            try:
                market_price = float(price_text)
                if not np.isfinite(market_price) or market_price <= 0:
                    st.error("Market price must be a positive numeric INR/share value. P/E is unavailable until a valid price is entered.")
                    market_price = np.nan
            except ValueError:
                st.error("Enter market price as a number in INR/share, without currency symbols or unit text.")
        f["PAT margin (%) — derived"] = [pat_margin(p, r) for p, r in zip(f.pat_crore, f.revenue_crore)]
        f["Debt-to-equity (x) — derived"] = [debt_to_equity(d, n) for d, n in zip(f.total_borrowings_crore, f.net_worth_crore)]
        f["P/E (x) — derived"] = [implied_pe(market_price, eps) for eps in f.eps]
        f["Revenue growth (%) — derived"] = annual_growth_by_period(f.financial_year, f.revenue_crore)
        f["Profit growth (%) — derived"] = annual_growth_by_period(f.financial_year, f.pat_crore)
        display = f.rename(columns={
            "revenue_crore": "Revenue (INR crore)", "ebitda_crore": "EBITDA (INR crore)",
            "pat_crore": "PAT (INR crore)", "total_borrowings_crore": "Total borrowings (INR crore)",
            "net_worth_crore": "Net worth (INR crore)", "eps": "EPS (INR/share)",
        }).copy()
        display["Data label"] = display.data_status.map(row_data_label)
        display["Freshness"] = display.source_date.map(source_freshness)
        display = display.where(pd.notna(display), "Unavailable")
        st.dataframe(display, use_container_width=True, hide_index=True)
        st.download_button("Download selected financial CSV", f.to_csv(index=False).encode("utf-8"), file_name=f"financials_{selected}.csv", mime="text/csv")
        st.caption("Derived formulas: revenue/profit growth = (current ÷ prior − 1) × 100; PAT margin = PAT ÷ revenue × 100; debt-to-equity = borrowings ÷ net worth; P/E = entered market price ÷ EPS. Growth requires a positive prior value; other ratios require positive denominators. Missing values remain unavailable.")
        chart_cols = [c for c in ["revenue_crore", "ebitda_crore", "pat_crore"] if f[c].notna().any()]
        if chart_cols:
            st.plotly_chart(px.line(f, x="financial_year", y=chart_cols, markers=True, title="Supplied company financials (INR crore)"), use_container_width=True)
        else:
            st.info("No revenue, EBITDA or PAT values were supplied for this IPO; the chart is unavailable rather than zero-filled.")
        st.caption("Source URLs, source dates, and data-status labels are retained in the financial records.")

    st.markdown("#### Peer comparison")
    selected_peers = peers[peers.ipo_id.astype(str).eq(str(selected))].copy() if selected and not peers.empty else pd.DataFrame()
    if selected_peers.empty:
        st.info("No peer reference records have been saved for this IPO yet. Add sourced peer rows in Data Management → Peer data.")
    else:
        comparison_rows = []
        if not f.empty:
            latest = f.iloc[-1]
            company = master.loc[master.ipo_id.astype(str).eq(str(selected)), "company_name"] if not master.empty else pd.Series(dtype=object)
            comparison_rows.append({
                "Company / peer": str(company.iloc[0]) if not company.empty else str(selected),
                "Reporting period": str(latest.financial_year),
                "Revenue (INR crore)": latest.revenue_crore, "PAT (INR crore)": latest.pat_crore,
                "PAT margin (%)": pat_margin(latest.pat_crore, latest.revenue_crore),
                "P/E (x)": latest.get("P/E (x) — derived", np.nan),
                "Data label": row_data_label(latest.data_status), "Source URL": latest.source_url,
                "Source date": latest.source_date,
            })
        for peer in selected_peers.itertuples(index=False):
            peer_revenue, peer_pat = getattr(peer, "revenue_cr", np.nan), getattr(peer, "pat_cr", np.nan)
            comparison_rows.append({
                "Company / peer": str(peer.peer_name), "Reporting period": str(peer.period),
                "Revenue (INR crore)": peer_revenue, "PAT (INR crore)": peer_pat,
                "PAT margin (%)": pat_margin(peer_pat, peer_revenue), "P/E (x)": getattr(peer, "pe_ratio", np.nan),
                "Data label": row_data_label(getattr(peer, "data_status", "MANUAL")),
                "Source URL": getattr(peer, "source_url", ""), "Source date": getattr(peer, "reporting_date", ""),
            })
        peer_comparison = pd.DataFrame(comparison_rows)
        st.dataframe(peer_comparison.where(pd.notna(peer_comparison), "Unavailable"), use_container_width=True, hide_index=True)
        chart_metrics = [column for column in ("Revenue (INR crore)", "PAT (INR crore)")
                         if pd.to_numeric(peer_comparison[column], errors="coerce").notna().any()]
        if chart_metrics:
            st.plotly_chart(px.bar(peer_comparison, x="Company / peer", y=chart_metrics, barmode="group",
                                   title="Saved company and peer financials (INR crore)"), use_container_width=True)
        st.caption("Peer figures and reporting periods are user-entered source records. Compare only when their accounting basis and periods are compatible.")

elif page == "Scenario Simulator":
    st.subheader("Scenario Simulator")
    st.warning("USER ASSUMPTION — bear, base and bull listing prices are entered by you. They are not predicted, guaranteed, verified listing prices or GMP.")
    st.info("Educational use only. Outputs are arithmetic scenarios, not investment advice or a recommendation. Actual allotment, execution prices, liquidity, costs and taxes may differ.")
    selected = st.session_state.get("active_ipo_id")
    record = master.loc[master.ipo_id.astype(str).eq(selected)].iloc[0] if selected and not master.empty and master.ipo_id.astype(str).eq(selected).any() else None
    if record is not None and str(record.get("data_status", "")).upper() == "DEMO":
        st.warning("DEMO ONLY — the selected IPO record is synthetic. Confirm issue price and lot size from a reliable source before using them.")
    default_issue = (float(record.issue_price) if record is not None and pd.notna(record.issue_price) and record.issue_price > 0 else None)
    default_lot = (int(record.lot_size) if record is not None and pd.notna(record.lot_size) and record.lot_size > 0 else None)
    if default_issue is None:
        st.caption("No issue price is saved for the selected IPO. Enter the verified issue price; the price band is not substituted.")
    else:
        st.caption("Starting issue price and lot size are from the selected IPO record. Verify them before use; you can edit every input.")

    sim_key = str(selected or "manual")
    if st.button("Reset to selected IPO values", key=f"scenario_reset_{sim_key}"):
        st.session_state[f"issue_{sim_key}"] = default_issue
        st.session_state[f"lot_{sim_key}"] = default_lot
        st.session_state[f"lots_{sim_key}"] = 1
        reference = default_issue
        for key, value in (("bear", max(.01, round(reference * .8, 2)) if reference else None), ("base", max(.01, round(reference, 2)) if reference else None), ("bull", max(.01, round(reference * 1.2, 2)) if reference else None)):
            st.session_state[f"scenario_{key}_{sim_key}"] = value
        st.rerun()
    a, b, c = st.columns(3)
    issue_price = a.number_input("Issue price per share (₹)", min_value=0.01, value=default_issue, step=1.0, format="%.2f", key=f"issue_{sim_key}")
    lot_size = b.number_input("Lot size (shares)", min_value=1, value=default_lot, step=1, key=f"lot_{sim_key}")
    number_lots = c.number_input("Number of lots", min_value=1, value=1, step=1, key=f"lots_{sim_key}")
    st.markdown("#### Listing-price assumptions")
    x, y, z = st.columns(3)
    assumption_defaults = (max(0.01, round(issue_price * 0.8, 2)), max(0.01, round(issue_price, 2)), max(0.01, round(issue_price * 1.2, 2))) if issue_price is not None else (None, None, None)
    bear = x.number_input("Bear — USER ASSUMPTION (₹)", min_value=0.01, value=assumption_defaults[0], step=1.0, format="%.2f", key=f"scenario_bear_{sim_key}")
    base = y.number_input("Base — USER ASSUMPTION (₹)", min_value=0.01, value=assumption_defaults[1], step=1.0, format="%.2f", key=f"scenario_base_{sim_key}")
    bull = z.number_input("Bull — USER ASSUMPTION (₹)", min_value=0.01, value=assumption_defaults[2], step=1.0, format="%.2f", key=f"scenario_bull_{sim_key}")
    use_charges = st.checkbox("Include optional transaction costs, taxes and other charges", value=False)
    transaction_cost_pct = tax_pct = other_charges = 0.0
    if use_charges:
        st.caption("Illustrative convention: transaction cost % and tax % each apply to both buy-side investment and scenario sale value; other charges are a fixed total INR amount deducted once. Enter only estimates you have verified. These inputs are excluded unless this box is enabled.")
        c1, c2, c3 = st.columns(3)
        transaction_cost_pct = c1.number_input("Transaction cost (%)", min_value=0.0, max_value=100.0, value=0.0, step=0.1)
        tax_pct = c2.number_input("Tax (%)", min_value=0.0, max_value=100.0, value=0.0, step=0.1)
        other_charges = c3.number_input("Other fixed charges (₹)", min_value=0.0, value=0.0, step=10.0)
    assumptions = {"Bear": bear, "Base": base, "Bull": bull}
    try:
        if issue_price is None or lot_size is None or number_lots is None or any(value is None for value in assumptions.values()):
            st.info("Enter a positive issue price, whole-number lot size, number of lots, and all three USER ASSUMPTION prices to calculate scenarios.")
            st.stop()
        base_result = calculate_scenario(issue_price, int(lot_size), int(number_lots), base)
        comparison = scenario_comparison(issue_price, int(lot_size), int(number_lots), assumptions,
                                        transaction_cost_pct=transaction_cost_pct, tax_pct=tax_pct,
                                        other_charges=other_charges)
        st.markdown("#### Position summary")
        m1, m2, m3 = st.columns(3)
        m1.metric("Investment amount", f"₹{base_result['investment']:,.2f}")
        m2.metric("Shares purchased", f"{base_result['shares']:,}")
        m3.metric("Break-even price", f"₹{base_result['break_even_price']:,.2f} per share")
        st.markdown("#### Scenario comparison")
        st.dataframe(comparison.style.format({c: "₹{:,.2f}" if "₹" in c else "{:,.2f}" for c in comparison.columns if c != "Scenario"}), use_container_width=True, hide_index=True)
        st.download_button("Download scenario comparison CSV", comparison.to_csv(index=False).encode("utf-8"), file_name="ipo_scenario_comparison.csv", mime="text/csv")
        st.plotly_chart(px.bar(comparison, x="Scenario", y="Gross P/L (₹)", color="Scenario", title="Gross profit / loss by USER ASSUMPTION (₹)"), use_container_width=True)
        st.caption("Gross formulas: investment = issue price × lot size × lots; shares = lot size × lots; scenario value = assumed listing price × shares; gross P/L = scenario value − investment; gross return = gross P/L ÷ investment × 100; break-even price = investment ÷ shares.")
        if use_charges:
            st.caption("Optional net P/L = gross P/L − [(transaction cost % + tax %) × (investment + scenario value)] − fixed other charges. Gross outputs above exclude charges.")
        else:
            st.caption("Optional costs and taxes are disabled and excluded from all displayed calculations.")

        st.markdown("#### Listing-price sensitivity")
        default_prices = sorted(set(round(issue_price * multiplier, 2) for multiplier in (0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5) if issue_price * multiplier > 0))
        price_text = st.text_input("Sensitivity listing prices (₹, comma-separated USER ASSUMPTIONS)", value=", ".join(f"{p:g}" for p in default_prices), help="Enter one or more positive listing-price assumptions, separated by commas.")
        try:
            sensitivity_prices = [float(item.strip()) for item in price_text.split(",") if item.strip()]
            if not sensitivity_prices:
                st.info("Enter at least one positive listing-price assumption to show sensitivity.")
            else:
                sens = sensitivity_table(issue_price, int(lot_size), int(number_lots), sensitivity_prices,
                                         transaction_cost_pct=transaction_cost_pct, tax_pct=tax_pct,
                                         other_charges=other_charges)
                st.dataframe(sens.style.format({c: "₹{:,.2f}" if "₹" in c else "{:,.2f}" for c in sens.columns}), use_container_width=True, hide_index=True)
                st.plotly_chart(px.line(sens, x="USER ASSUMPTION listing price (₹)", y="Gross P/L (₹)", markers=True, title="Sensitivity to user-assumed listing price"), use_container_width=True)
                st.download_button("Download sensitivity CSV", sens.to_csv(index=False).encode("utf-8"), file_name="ipo_scenario_sensitivity.csv", mime="text/csv")
        except ValueError as exc:
            st.error(f"Invalid sensitivity input: {exc}. Use positive numeric prices separated by commas.")
    except ValueError as exc:
        st.error(f"Scenario inputs are invalid: {exc}")

elif page == "Data Management":
    st.subheader("IPO Data Management")
    st.caption("Add and maintain real IPO records without editing code. Changes are saved to this instance CSV files. Public hosting may have ephemeral storage and does not provide safe shared concurrent writes; use a persistent volume or database for multi-user production.")
    ipo_tab, financial_tab, subscription_tab, peer_tab, source_tab = st.tabs(["IPO details", "Financial statements", "Subscription data", "Peer data", "Source documents"])

    template_columns = {
        "ipo_master": ["ipo_id","company_name","segment","exchange","status","open_date","close_date","issue_price","price_band_low","price_band_high","lot_size","issue_size_crore","fresh_issue_crore","offer_for_sale_crore","listing_price","listing_date","sector","drhp_url","rhp_url","source_url","source_date","data_status"],
        "financials": ["ipo_id","financial_year","revenue_crore","ebitda_crore","pat_crore","total_borrowings_crore","net_worth_crore","eps","source_url","source_date","data_status"],
        "subscription": ["ipo_id","category","subscription_multiple","as_of","data_status","source_url","reporting_date"],
        "peers": ["ipo_id","peer_name","period","market_cap_cr","revenue_cr","pat_cr","pe_ratio","data_status","source_url","reporting_date"],
    }
    key_columns = {"ipo_master": ["ipo_id"], "financials": ["ipo_id","financial_year"], "subscription": ["ipo_id","category","as_of"], "peers": ["ipo_id","peer_name","period"]}

    def render_csv_tools(dataset_name: str):
        frame = st.session_state.datasets[dataset_name]
        st.markdown("#### CSV template, backup and import")
        left, right = st.columns(2)
        left.download_button(f"Download {dataset_name} CSV template", pd.DataFrame(columns=template_columns[dataset_name]).to_csv(index=False).encode("utf-8"), file_name=f"{dataset_name}_template.csv", mime="text/csv", key=f"template_{dataset_name}")
        right.download_button(f"Backup current {dataset_name} before import", frame.to_csv(index=False).encode("utf-8"), file_name=f"{dataset_name}_backup.csv", mime="text/csv", key=f"backup_{dataset_name}")
        backup_confirmed = st.checkbox("I downloaded or otherwise saved a backup before this bulk import", key=f"backup_confirm_{dataset_name}")
        upload = st.file_uploader(f"Upload {dataset_name} CSV", type=["csv"], key=f"manager_upload_{dataset_name}")
        if not upload:
            return
        try:
            incoming = parse_uploaded_csv(upload, dataset_name)
            keys = key_columns[dataset_name]
            duplicate_inside = incoming.duplicated(keys, keep=False)
            existing = frame.copy()
            for col in keys:
                existing[col] = existing[col].fillna("").astype(str)
                incoming[col] = incoming[col].fillna("").astype(str)
            existing_keys = set(map(tuple, existing[keys].to_numpy())) if not existing.empty else set()
            incoming_keys = list(map(tuple, incoming[keys].to_numpy()))
            conflicts = [tuple_key in existing_keys for tuple_key in incoming_keys]
            incoming["Import check"] = ["DUPLICATE IN FILE" if duplicate_inside.iloc[i] else "ALREADY EXISTS" if conflicts[i] else "NEW RECORD" for i in range(len(incoming))]
            st.success(f"CSV validated: {len(incoming)} rows and required columns are valid.")
            if duplicate_inside.any(): st.error("Duplicate record keys occur inside the uploaded file. Remove duplicates before import.")
            if any(conflicts): st.warning("Some record keys already exist. Import is append-only and will not overwrite existing records; remove duplicates or edit records in the form.")
            if dataset_name == "ipo_master" and "data_status" in incoming:
                verified_ids = set(frame.loc[frame.data_status.astype(str).eq("VERIFIED"), "ipo_id"].astype(str)) if not frame.empty else set()
                if any(ident in verified_ids and str(status) == "DEMO" for ident, status in zip(incoming.ipo_id.astype(str), incoming.data_status.astype(str))):
                    st.error("A DEMO row cannot replace a VERIFIED IPO record. Verified rows are protected.")
            st.dataframe(incoming.where(pd.notna(incoming), "Unavailable"), use_container_width=True, hide_index=True)
            ready = backup_confirmed and not duplicate_inside.any() and not any(conflicts)
            if st.button(f"Import {dataset_name} new rows", type="primary", disabled=not ready, key=f"import_{dataset_name}"):
                clean = incoming.drop(columns=["Import check"])
                persist_dataset(dataset_name, append_import_only(frame, clean, dataset_name))
                for _, row in clean.iterrows():
                    value = lambda column: "" if pd.isna(row.get(column, "")) else str(row.get(column, ""))
                    append_provenance(dataset_name, "|".join(str(row.get(k, "")) for k in keys), action="CSV import",
                        source_url=value("source_url"), observation_date=value("source_date") or value("as_of") or value("reporting_date"),
                        reporting_period=value("financial_year") or value("period") or value("reporting_date"), data_status=value("data_status") or "MANUAL")
                st.success("New records imported and saved. Existing rows were not overwritten.")
                st.rerun()
        except DataValidationError as exc:
            st.error(f"CSV validation failed: {exc}")

    master_now = st.session_state.datasets["ipo_master"]
    ipo_ids = master_now.ipo_id.astype(str).tolist() if not master_now.empty else []
    active_ipo = st.session_state.get("active_ipo_id", ipo_ids[0] if ipo_ids else "")

    with ipo_tab:
        st.markdown("#### Add a new IPO or edit an existing one")
        action = st.radio("IPO action", ["Add new", "Edit existing"], horizontal=True, key="manager_ipo_action")
        selected_id = st.selectbox("Select IPO", ipo_ids, index=ipo_ids.index(active_ipo) if active_ipo in ipo_ids else 0, key="manager_ipo_selected") if ipo_ids else ""
        old = master_now.loc[master_now.ipo_id.astype(str).eq(selected_id)].iloc[0].to_dict() if action == "Edit existing" and selected_id else {}
        editor_key = selected_id if old else "new"
        if old.get("data_status") == "VERIFIED": st.warning("VERIFIED record selected. Changes require explicit re-verification acknowledgement and a source URL/date.")
        with st.form(f"ipo_form_{editor_key}"):
            ident = st.text_input("IPO ID", value=input_text(old.get("ipo_id", "")), key=f"ipo_{editor_key}_id")
            company = st.text_input("Company / IPO name", value=input_text(old.get("company_name", "")), key=f"ipo_{editor_key}_name")
            a,b,c = st.columns(3)
            segments = ["Mainboard", "SME"]
            segment_old = str(old.get("segment", "Mainboard"))
            segment = a.selectbox("Segment", segments, index=segments.index(segment_old) if segment_old in segments else 0, key=f"ipo_{editor_key}_segment")
            statuses = ["Upcoming", "Open", "Closed", "Listed"]
            status_old = str(old.get("status", "Upcoming"))
            ipo_status = b.selectbox("Status", statuses, index=statuses.index(status_old) if status_old in statuses else 0, key=f"ipo_{editor_key}_status")
            exchange = c.text_input("Exchange", value=input_text(old.get("exchange", "NSE")), key=f"ipo_{editor_key}_exchange")
            a,b,c = st.columns(3)
            opening = a.text_input("Open date (YYYY-MM-DD)", value=input_text(old.get("open_date", "")), key=f"ipo_{editor_key}_open")
            closing = b.text_input("Close date (YYYY-MM-DD)", value=input_text(old.get("close_date", "")), key=f"ipo_{editor_key}_close")
            listing_date = c.text_input("Listing date (YYYY-MM-DD)", value=input_text(old.get("listing_date", "")), key=f"ipo_{editor_key}_listing_date")
            def old_num(name):
                value = old.get(name)
                return float(value) if pd.notna(value) else 0.0
            a,b,c = st.columns(3)
            issue = a.number_input("Issue price (₹/share; 0 = unavailable)", min_value=0.0, value=old_num("issue_price"), key=f"ipo_{editor_key}_issue")
            low = b.number_input("Price band low (₹; 0 = unavailable)", min_value=0.0, value=old_num("price_band_low"), key=f"ipo_{editor_key}_low")
            high = c.number_input("Price band high (₹; 0 = unavailable)", min_value=0.0, value=old_num("price_band_high"), key=f"ipo_{editor_key}_high")
            a,b,c = st.columns(3)
            lot = a.number_input("Lot size (shares; 0 = unavailable)", min_value=0, value=int(old_num("lot_size")), key=f"ipo_{editor_key}_lot")
            issue_size = b.number_input("Issue size (INR crore)", min_value=0.0, value=old_num("issue_size_crore"), key=f"ipo_{editor_key}_size")
            fresh = c.number_input("Fresh issue (INR crore)", min_value=0.0, value=old_num("fresh_issue_crore"), key=f"ipo_{editor_key}_fresh")
            a,b,c = st.columns(3)
            ofs = a.number_input("Offer for sale (INR crore)", min_value=0.0, value=old_num("offer_for_sale_crore"), key=f"ipo_{editor_key}_ofs")
            listing = b.number_input("Verified listing price (₹; 0 = unavailable)", min_value=0.0, value=old_num("listing_price"), key=f"ipo_{editor_key}_listing")
            sector = c.text_input("Sector", value=input_text(old.get("sector", "")), key=f"ipo_{editor_key}_sector")
            data_status_old = str(old.get("data_status", "MANUAL"))
            data_status = st.selectbox("Data status", ["MANUAL", "VERIFIED", "DEMO"], index=["MANUAL", "VERIFIED", "DEMO"].index(data_status_old) if data_status_old in ["MANUAL", "VERIFIED", "DEMO"] else 0, key=f"ipo_{editor_key}_data_status")
            source = st.text_input("Source URL", value=input_text(old.get("source_url", "")), key=f"ipo_{editor_key}_source")
            source_date = st.text_input("Source observation date (YYYY-MM-DD)", value=input_text(old.get("source_date", "")), key=f"ipo_{editor_key}_source_date")
            acknowledge = st.checkbox("I rechecked the source and authorize replacing this VERIFIED record", key=f"ipo_{editor_key}_verified_ack") if data_status_old == "VERIFIED" else True
            save_ipo = st.form_submit_button("Save IPO" if not old else "Update IPO")
            cancel_ipo = st.form_submit_button("Cancel")
        if save_ipo:
            try:
                if old and old.get("data_status") == "VERIFIED" and not acknowledge: raise DataValidationError("Confirm source re-verification before editing this VERIFIED record.")
                if not old and ident.strip() in set(master_now.ipo_id.astype(str)): raise DataValidationError("That IPO ID already exists.")
                item = {"ipo_id":ident.strip(),"company_name":company.strip(),"segment":segment,"exchange":exchange.strip(),"status":ipo_status,"open_date":opening.strip(),"close_date":closing.strip(),"issue_price":issue or np.nan,"price_band_low":low or np.nan,"price_band_high":high or np.nan,"lot_size":lot or np.nan,"issue_size_crore":issue_size or np.nan,"fresh_issue_crore":fresh or np.nan,"offer_for_sale_crore":ofs or np.nan,"listing_price":listing or np.nan,"listing_date":listing_date.strip(),"sector":sector.strip(),"drhp_url":old.get("drhp_url", ""),"rhp_url":old.get("rhp_url", ""),"source_url":source.strip(),"source_date":source_date.strip(),"data_status":data_status}
                candidate = master_now.copy()
                if old: candidate = candidate.loc[~candidate.ipo_id.astype(str).eq(selected_id)]
                candidate = pd.concat([candidate,pd.DataFrame([item])],ignore_index=True)
                persist_dataset("ipo_master",candidate,provenance={"record_key":ident.strip(),"action":"manual add" if not old else "manual update","source_url":source,"observation_date":source_date,"reporting_period":"","data_status":data_status})
                st.session_state.pending_active_ipo_id = ident.strip(); st.success("IPO saved locally. Connected pages will use the updated record on the next render."); st.rerun()
            except (DataValidationError,ValueError,OSError) as exc: st.error(f"IPO could not be saved: {exc}")
        if cancel_ipo: st.info("Edit cancelled; no changes were saved.")
        if old:
            with st.expander("Delete IPO and its related financial, subscription and peer rows"):
                confirmed = st.checkbox(f"Confirm deletion of {selected_id} and related data",key=f"delete_confirm_{selected_id}")
                if st.button("Delete selected IPO",disabled=not confirmed,key=f"delete_ipo_{selected_id}"):
                    for dataset_name in ("ipo_master","financials","subscription","peers"):
                        frame = st.session_state.datasets[dataset_name]
                        save_dataset(dataset_name,frame.loc[frame.ipo_id.astype(str).ne(selected_id)])
                        st.session_state.datasets[dataset_name]=load_dataset(dataset_name)
                    append_provenance("ipo_master",selected_id,action="delete",data_status=str(old.get("data_status","MANUAL")))
                    st.success("IPO and related rows deleted."); st.rerun()
        render_csv_tools("ipo_master")

    with financial_tab:
        st.markdown("#### Annual financial statements")
        fin = st.session_state.datasets["financials"]
        choices = [f"{r.ipo_id} · {r.financial_year}" for r in fin.itertuples()] if not fin.empty else []
        choice = st.selectbox("Financial record", ["Add new"]+choices, key="manager_fin_choice")
        old = fin.iloc[choices.index(choice)].to_dict() if choice != "Add new" else {}
        fin_ipo_options = sorted(set(ipo_ids + ([str(old.get("ipo_id"))] if old else [])))
        target = str(old.get("ipo_id",active_ipo))
        if old.get("data_status")=="VERIFIED": st.warning("VERIFIED financial record. Confirm source re-verification before updating.")
        with st.form("financial_editor"):
            fin_ipo = st.selectbox("IPO ID",fin_ipo_options,index=fin_ipo_options.index(target) if target in fin_ipo_options else 0) if fin_ipo_options else st.text_input("IPO ID")
            year = st.text_input("Financial year / reporting period",value=input_text(old.get("financial_year","")),placeholder="FY2024 or FY2023-24")
            fields=["revenue_crore","ebitda_crore","pat_crore","total_borrowings_crore","net_worth_crore","eps"]; numeric={}
            cols=st.columns(3)
            for i,field in enumerate(fields): numeric[field]=cols[i%3].text_input(f"{field.replace('_',' ')} ({'INR/share' if field=='eps' else 'INR crore'})",value=input_text(old.get(field,"")),help="Leave blank if unavailable; enter zero only when zero is the actual reported value.")
            fs=st.text_input("Source URL",value=input_text(old.get("source_url",""))); fd=st.text_input("Source observation date (YYYY-MM-DD)",value=input_text(old.get("source_date","")))
            fstatus=st.selectbox("Data status",["MANUAL","VERIFIED","DEMO"],index=["MANUAL","VERIFIED","DEMO"].index(str(old.get("data_status","MANUAL"))) if str(old.get("data_status","MANUAL")) in ["MANUAL","VERIFIED","DEMO"] else 0)
            ack=st.checkbox("I rechecked the source and authorize replacing this VERIFIED financial record") if old.get("data_status")=="VERIFIED" else True
            save_fin=st.form_submit_button("Save financial statement" if not old else "Update financial statement"); cancel_fin=st.form_submit_button("Cancel")
        if save_fin:
            try:
                if old.get("data_status")=="VERIFIED" and not ack: raise DataValidationError("Confirm re-verification before editing this VERIFIED financial record.")
                parsed={k:(float(v) if v.strip() else np.nan) for k,v in numeric.items()}
                if any(pd.notna(v) and not np.isfinite(v) for v in parsed.values()): raise ValueError("Financial amounts must be finite numbers.")
                row={"ipo_id":str(fin_ipo),"financial_year":year.strip(),**parsed,"source_url":fs.strip(),"source_date":fd.strip(),"data_status":fstatus}
                updated=fin.copy()
                if old: updated=updated.loc[~((updated.ipo_id.astype(str)==str(old["ipo_id"]))&(updated.financial_year.astype(str)==str(old["financial_year"])))]
                persist_dataset("financials",pd.concat([updated,pd.DataFrame([row])],ignore_index=True),provenance={"record_key":f"{fin_ipo}|{year}","action":"manual add/update","source_url":fs,"observation_date":fd,"reporting_period":year,"data_status":fstatus})
                st.success("Financial statement saved."); st.rerun()
            except (ValueError,DataValidationError,OSError) as exc: st.error(f"Financial record could not be saved: {exc}")
        if cancel_fin: st.info("Edit cancelled; no changes were saved.")
        if old:
            confirm_fin_delete=st.checkbox(f"Confirm deletion of {choice}",key="confirm_delete_financial")
            if st.button("Delete selected financial record",disabled=not confirm_fin_delete,key="delete_financial"):
                persist_dataset("financials",fin.loc[~((fin.ipo_id.astype(str)==str(old["ipo_id"]))&(fin.financial_year.astype(str)==str(old["financial_year"])))])
                append_provenance("financials",f"{old['ipo_id']}|{old['financial_year']}",action="delete",data_status=str(old.get("data_status","MANUAL")))
                st.success("Financial record deleted."); st.rerun()
        render_csv_tools("financials")

    with subscription_tab:
        st.markdown("#### Subscription observations")
        sub=st.session_state.datasets["subscription"].copy()
        for col,default in (("data_status","MANUAL"),("source_url",""),("reporting_date","")):
            if col not in sub: sub[col]=default
        subopts=[f"{r.ipo_id} · {r.category} · {r.as_of}" for r in sub.itertuples()] if not sub.empty else []
        subchoice=st.selectbox("Subscription record",["Add new"]+subopts,key="manager_sub_choice"); old=sub.iloc[subopts.index(subchoice)].to_dict() if subchoice!="Add new" else {}
        with st.form("subscription_form"):
            opts=sorted(set(ipo_ids+([str(old.get("ipo_id"))] if old else [])))
            si=str(old.get("ipo_id",active_ipo)); ipo_sub=st.selectbox("IPO ID",opts,index=opts.index(si) if si in opts else 0) if opts else st.text_input("IPO ID")
            cats=["QIB","NII","RETAIL","Total"]; cat=str(old.get("category","QIB")).upper(); category=st.selectbox("Category",cats,index=cats.index(cat) if cat in cats else 0)
            multiple=st.text_input("Subscription multiple",value=input_text(old.get("subscription_multiple","")),help="Leave unavailable figures blank.")
            obs=st.text_input("Observation date (YYYY-MM-DD)",value=input_text(old.get("as_of",""))); src=st.text_input("Source URL",value=input_text(old.get("source_url","")))
            ss=st.selectbox("Data status",["MANUAL","VERIFIED","DEMO"],index=["MANUAL","VERIFIED","DEMO"].index(str(old.get("data_status","MANUAL"))) if str(old.get("data_status","MANUAL")) in ["MANUAL","VERIFIED","DEMO"] else 0)
            ack=st.checkbox("I rechecked the source and authorize replacing this VERIFIED observation") if old.get("data_status")=="VERIFIED" else True
            save_sub=st.form_submit_button("Save subscription observation" if not old else "Update subscription observation"); cancel_sub=st.form_submit_button("Cancel")
        if save_sub:
            try:
                if old.get("data_status")=="VERIFIED" and not ack: raise DataValidationError("Confirm source re-verification before editing this VERIFIED observation.")
                value=float(multiple.strip()) if multiple.strip() else np.nan
                row={"ipo_id":str(ipo_sub),"category":category,"subscription_multiple":value,"as_of":obs.strip(),"data_status":ss,"source_url":src.strip(),"reporting_date":obs.strip()}
                updated=sub.copy()
                if old: updated=updated.loc[~((updated.ipo_id.astype(str)==str(old["ipo_id"]))&(updated.category.astype(str)==str(old["category"]))&(updated.as_of.astype(str)==str(old["as_of"])))]
                persist_dataset("subscription",pd.concat([updated,pd.DataFrame([row])],ignore_index=True),provenance={"record_key":f"{ipo_sub}|{category}|{obs}","action":"manual add/update","source_url":src,"observation_date":obs,"reporting_period":obs,"data_status":ss})
                st.success("Subscription data saved."); st.rerun()
            except (ValueError,DataValidationError,OSError) as exc: st.error(f"Subscription record could not be saved: {exc}")
        if cancel_sub: st.info("Edit cancelled; no changes were saved.")
        if old:
            confirm_sub_delete=st.checkbox(f"Confirm deletion of {subchoice}",key="confirm_delete_subscription")
            if st.button("Delete selected subscription observation",disabled=not confirm_sub_delete,key="delete_subscription"):
                persist_dataset("subscription",sub.loc[~((sub.ipo_id.astype(str)==str(old["ipo_id"]))&(sub.category.astype(str)==str(old["category"]))&(sub.as_of.astype(str)==str(old["as_of"])))])
                append_provenance("subscription",f"{old['ipo_id']}|{old['category']}|{old['as_of']}",action="delete",data_status=str(old.get("data_status","MANUAL")))
                st.success("Subscription observation deleted."); st.rerun()
        render_csv_tools("subscription")

    with peer_tab:
        st.markdown("#### Peer reference records")
        peer=st.session_state.datasets["peers"].copy()
        for col,default in (("pe_ratio",np.nan),("data_status","MANUAL"),("source_url",""),("reporting_date","")):
            if col not in peer: peer[col]=default
        peeropts=[f"{r.ipo_id} · {r.peer_name} · {r.period}" for r in peer.itertuples()] if not peer.empty else []
        peerchoice=st.selectbox("Peer record",["Add new"]+peeropts,key="manager_peer_choice"); old=peer.iloc[peeropts.index(peerchoice)].to_dict() if peerchoice!="Add new" else {}
        with st.form("peer_form"):
            opts=sorted(set(ipo_ids+([str(old.get("ipo_id"))] if old else []))); pi=str(old.get("ipo_id",active_ipo)); peer_ipo=st.selectbox("IPO ID",opts,index=opts.index(pi) if pi in opts else 0) if opts else st.text_input("IPO ID")
            name=st.text_input("Peer company name",value=input_text(old.get("peer_name",""))); period=st.text_input("Reporting period",value=input_text(old.get("period","")))
            pnums={}; cols=st.columns(4)
            for i,field in enumerate(["market_cap_cr","revenue_cr","pat_cr","pe_ratio"]): pnums[field]=cols[i].text_input(field.replace("_"," "),value=input_text(old.get(field,"")),help="Leave blank when unavailable.")
            psource=st.text_input("Source URL",value=input_text(old.get("source_url",""))); pdate=st.text_input("Observation / reporting date",value=input_text(old.get("reporting_date","")))
            pstatus=st.selectbox("Data status",["MANUAL","VERIFIED","DEMO"]); ack=st.checkbox("I rechecked and authorize replacing this VERIFIED peer record") if old.get("data_status")=="VERIFIED" else True
            save_peer=st.form_submit_button("Save peer record" if not old else "Update peer record"); cancel_peer=st.form_submit_button("Cancel")
        if save_peer:
            try:
                if old.get("data_status")=="VERIFIED" and not ack: raise DataValidationError("Confirm source re-verification before editing this VERIFIED peer record.")
                vals={k:(float(v) if v.strip() else np.nan) for k,v in pnums.items()}
                if any(pd.notna(v) and not np.isfinite(v) for v in vals.values()): raise ValueError("Peer metrics must be finite numbers.")
                row={"ipo_id":str(peer_ipo),"peer_name":name.strip(),"period":period.strip(),**vals,"data_status":pstatus,"source_url":psource.strip(),"reporting_date":pdate.strip()}
                updated=peer.copy()
                if old: updated=updated.loc[~((updated.ipo_id.astype(str)==str(old["ipo_id"]))&(updated.peer_name.astype(str)==str(old["peer_name"]))&(updated.period.astype(str)==str(old["period"])))]
                persist_dataset("peers",pd.concat([updated,pd.DataFrame([row])],ignore_index=True),provenance={"record_key":f"{peer_ipo}|{name}|{period}","action":"manual add/update","source_url":psource,"observation_date":pdate,"reporting_period":period,"data_status":pstatus})
                st.success("Peer record saved."); st.rerun()
            except (ValueError,DataValidationError,OSError) as exc: st.error(f"Peer record could not be saved: {exc}")
        if cancel_peer: st.info("Edit cancelled; no changes were saved.")
        if old:
            confirm_peer_delete=st.checkbox(f"Confirm deletion of {peerchoice}",key="confirm_delete_peer")
            if st.button("Delete selected peer record",disabled=not confirm_peer_delete,key="delete_peer"):
                persist_dataset("peers",peer.loc[~((peer.ipo_id.astype(str)==str(old["ipo_id"]))&(peer.peer_name.astype(str)==str(old["peer_name"]))&(peer.period.astype(str)==str(old["period"])))])
                append_provenance("peers",f"{old['ipo_id']}|{old['peer_name']}|{old['period']}",action="delete",data_status=str(old.get("data_status","MANUAL")))
                st.success("Peer record deleted."); st.rerun()
        render_csv_tools("peers")

    with source_tab:
        st.markdown("#### Source documents and provenance")
        selected_source_id=st.selectbox("IPO for source documents",ipo_ids,index=ipo_ids.index(active_ipo) if active_ipo in ipo_ids else 0,key="source_ipo_select") if ipo_ids else ""
        if selected_source_id:
            selected_row=master_now.loc[master_now.ipo_id.astype(str).eq(selected_source_id)].iloc[0]
            st.write(f"**{selected_row.company_name}** · {selected_row.data_status} · IPO source date: {display_value(selected_row.source_date)}")
            record_history=load_provenance()
            record_history=record_history.loc[(record_history.dataset=="ipo_master")&(record_history.record_key.astype(str)==str(selected_source_id))] if not record_history.empty else record_history
            last_updated=record_history.last_updated_utc.iloc[-1] if not record_history.empty else "Unavailable (record predates local provenance tracking)"
            st.caption(f"Last updated: {last_updated}")
            for label,field in (("Source URL","source_url"),("DRHP","drhp_url"),("RHP","rhp_url")):
                url=selected_row.get(field,"")
                if pd.notna(url) and str(url).strip(): st.markdown(f"[{label}: {url}]({url})")
                else: st.caption(f"{label}: unavailable")
            st.markdown("##### Edit IPO source documents")
            with st.form(f"ipo_sources_{selected_source_id}"):
                verified_source=selected_row.get("data_status")=="VERIFIED"
                s_source=st.text_input("Primary source URL",value=input_text(selected_row.get("source_url","")))
                s_drhp=st.text_input("DRHP URL",value=input_text(selected_row.get("drhp_url","")))
                s_rhp=st.text_input("RHP URL",value=input_text(selected_row.get("rhp_url","")))
                s_date=st.text_input("Source observation date (YYYY-MM-DD)",value=input_text(selected_row.get("source_date","")))
                s_status=st.selectbox("Data status",["MANUAL","VERIFIED","DEMO"],index=["MANUAL","VERIFIED","DEMO"].index(str(selected_row.get("data_status","MANUAL"))) if str(selected_row.get("data_status","MANUAL")) in ["MANUAL","VERIFIED","DEMO"] else 0)
                source_ack=st.checkbox("I rechecked and authorize replacing VERIFIED provenance") if verified_source else True
                save_sources=st.form_submit_button("Save source documents")
                cancel_sources=st.form_submit_button("Cancel")
            if save_sources:
                try:
                    if verified_source and not source_ack: raise DataValidationError("Confirm source re-verification before changing VERIFIED provenance.")
                    edited=master_now.copy(); mask=edited.ipo_id.astype(str).eq(selected_source_id)
                    edited.loc[mask,"source_url"]=s_source.strip(); edited.loc[mask,"drhp_url"]=s_drhp.strip(); edited.loc[mask,"rhp_url"]=s_rhp.strip(); edited.loc[mask,"source_date"]=s_date.strip(); edited.loc[mask,"data_status"]=s_status
                    persist_dataset("ipo_master",edited,provenance={"record_key":selected_source_id,"action":"source documents updated","source_url":s_source,"observation_date":s_date,"data_status":s_status})
                    st.success("Source links and provenance saved."); st.rerun()
                except (DataValidationError,ValueError,OSError) as exc: st.error(f"Source documents could not be saved: {exc}")
            if cancel_sources: st.info("Source document changes cancelled.")
        provenance=load_provenance()
        if not provenance.empty:
            st.markdown("##### Saved record history")
            st.dataframe(provenance.sort_values("last_updated_utc",ascending=False),use_container_width=True,hide_index=True)
            st.download_button("Download provenance CSV",provenance.to_csv(index=False).encode("utf-8"),file_name="ipo_record_provenance.csv",mime="text/csv")
        st.markdown("#### Available automatic refresh")
        st.caption("NSE issue-information refresh has been tested for its supported response fields. It does not overwrite IPO records; a successful response must be reviewed and can be added as a separate MANUAL draft.")
        rc1,rc2=st.columns(2); symbol=rc1.text_input("NSE symbol"); series=rc2.selectbox("NSE series",["EQ","SME"])
        if st.button("Refresh NSE now",type="primary"):
            request_url=f"https://www.nseindia.com/api/ipo-detail?{urlencode({'series':series,'symbol':symbol.strip().upper()})}"
            try:
                result=NseIpoAdapter().fetch(symbol,series); st.session_state["last_nse_retrieval"]=result; append_retrieval(result)
                st.success(f"Refresh succeeded at {result.retrieved_at}. Verification remains review-required.")
            except (NseRetrievalError,ValueError,OSError) as exc:
                result=RetrievalResult("NSE Issue Information",request_url,datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z"),None,"UNAVAILABLE",False,{},str(exc)); st.session_state["last_nse_retrieval"]=result
                try: append_retrieval(result)
                except (ValueError,OSError): pass
                st.error(f"Refresh failed: {exc}. Saved records remain unchanged.")
        result=st.session_state.get("last_nse_retrieval")
        if result:
            st.caption(f"Response source: {result.source_url} · Retrieved (UTC): {result.retrieved_at} · Reporting period: {result.reporting_period or 'Unavailable'} · Status: {result.verification_status}")
            if result.success:
                age=pd.Timestamp.now(tz="UTC")-pd.to_datetime(result.retrieved_at,utc=True)
                missing=sum(value is None or (isinstance(value,str) and not value.strip()) for value in result.fields.values())
                st.warning(f"{'STALE' if age>pd.Timedelta(days=7) else 'CURRENT'} retrieval · {'INCOMPLETE' if missing else 'FIELD-COMPLETE'}: {missing} of {len(result.fields)} supported fields unavailable. Retrieval success is not human verification.")
                st.dataframe(pd.DataFrame([result.fields]).T.rename(columns={0:"Retrieved value"}).fillna("Unavailable"),use_container_width=True)
                st.info("Use the IPO details tab to enter reviewed values. Missing fields remain blank; retrieval does not automatically change a saved IPO.")
            else: st.error(f"UNAVAILABLE at {result.retrieved_at}: {result.message}. Existing saved records remain unchanged.")
        retrieval_history=load_retrieval_history()
        if not retrieval_history.empty:
            st.markdown("##### Refresh history")
            history_view=retrieval_history.tail(12).copy()
            history_view["availability"]=history_view.success.map({True:"Retrieved",False:"Unavailable"})
            history_times=pd.to_datetime(history_view.retrieved_at,errors="coerce",utc=True)
            history_view["freshness"]=np.where((pd.Timestamp.now(tz="UTC")-history_times)>pd.Timedelta(days=7),"STALE","Recent")
            st.dataframe(history_view[["source_name","source_url","retrieved_at","reporting_period","verification_status","availability","freshness","message"]],use_container_width=True,hide_index=True)
            st.download_button("Download source refresh history CSV",retrieval_history.to_csv(index=False).encode("utf-8"),file_name="ipo_retrieval_history.csv",mime="text/csv")
        st.markdown("#### Current subscription, financial and peer sources")
        for dataset_name in ("financials","subscription","peers"):
            frame=st.session_state.datasets[dataset_name]
            if not frame.empty:
                st.markdown(f"**{dataset_name.title()}**")
                st.dataframe(frame[[c for c in frame.columns if c in ["ipo_id","financial_year","category","peer_name","source_url","source_date","as_of","reporting_date","data_status"]]],use_container_width=True,hide_index=True)

else:
    st.subheader("Methodology & Disclosures")
    st.markdown("""
### Scope
This application supports Indian Mainboard and SME IPO records provided by the user. It is an offline research and scenario tool, not an investment recommendation.

### Data handling
- Packaged examples are synthetic and prominently labeled **DEMONSTRATION ONLY**. They are not real IPOs or actual financial, subscription, GMP, or listing data.
- No provider is contacted automatically. The user-initiated NSE Issue Information refresh is rate-limited and only creates a separate MANUAL draft after explicit action. Other sources remain available through manual entry/CSV import. Missing values remain missing; the app does not create actual market figures.
- Upload schemas are checked for required fields, numeric values, dates, duplicate IDs/periods, and basic IPO constraints. Manual additions, edits and accepted CSV imports are saved to the local CSV files in `data/` and survive app restarts on the same persistent filesystem. Public hosting may have ephemeral filesystems, multiple isolated replicas, and concurrent-write conflicts; use a persistent volume or database for shared production data.
- Prefer primary sources such as exchange filings and offer documents. Record `source_url` and `source_date` for sourced facts. Use `data_status` values VERIFIED, MANUAL, or DEMO; verified rows require both source fields, and a listing price is accepted only for a Listed, VERIFIED row.
- NSE issue retrieval is source-response checked, not human verification. Results require review, carry retrieval timestamps, and never replace existing verified records. See `SOURCES.md` for tested fields and manual-only sources.

### Primary source links
- [NSE Issue Information](https://www.nseindia.com/market-data/issue-information)
- [BSE Public Issues](https://www.bseindia.com/markets/publicIssues/DisplayIPO.aspx)
- [SEBI Public Issues filings](https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15)

### Calculations
- Revenue growth = (current period revenue / prior period revenue − 1) × 100.
- PAT margin = PAT / revenue × 100; EBITDA margin = EBITDA / revenue × 100.
- Debt / net worth = debt divided by net worth. Undefined ratios are shown as blank/NaN when the denominator is zero.
- Implied P/E = price / EPS; implied market capitalization = shares outstanding (crore) × price.
- Scenario investment = issue price per share × lot size × lots; shares = lot size × lots; scenario value = user-assumed listing price × shares; gross P/L = scenario value − investment; gross return = gross P/L ÷ investment × 100; break-even price = investment ÷ shares. Bear, Base, Bull and sensitivity prices are labeled USER ASSUMPTION, never forecasts or GMP.
- Optional scenario charges are excluded by default. When enabled, the entered transaction cost and tax rates each apply to investment plus scenario sale value; fixed other charges are applied once. Net P/L after optional charges = gross P/L − percentage charges − fixed charges. This is a user-supplied illustration, not tax guidance.

### Limitations
Ratios depend on the quality, accounting basis, units, and periods of the source data. The tool does not assess eligibility, allotment probability, taxes, fees, liquidity, or suitability. Validate values independently before use.
""")
