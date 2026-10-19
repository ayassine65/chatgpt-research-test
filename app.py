import json
import math
import uuid
from datetime import datetime, timezone

import gspread
import pandas as pd
import streamlit as st
import yfinance as yf
from google.oauth2 import service_account

st.set_page_config(page_title="Research Stock Storage Test", page_icon="🧪", layout="wide")
st.title("ChatGPT Research — Stock Storage Test v2.1")
st.info("ISOLATED TEST ONLY: This application opens only ChatGPT_Research_Integration_Test. It never opens the Wealth Command Center production spreadsheet.")

TEST_TITLE = "ChatGPT_Research_Integration_Test"
TEST_TAB = "RESEARCH_STOCKS_TEST"
HEADERS = [
    "Run ID", "Scan UTC", "Ticker", "Price ($)", "Price As Of", "Price Eligible $10-$225",
    "SMA 20 ($)", "SMA 50 ($)", "SMA 200 ($)", "Above SMA 20", "Above SMA 50", "Above SMA 200",
    "52W Low ($)", "52W High ($)", "Relative Volume 20D", "Next Earnings", "Earnings Status",
    "Revenue Growth (%)", "Operating Margin (%)", "Forward P/E", "Research Classification",
    "Data Status", "Price Source", "Notes",
]

def connection():
    raw = st.secrets["gcp_service_account_json"]
    account = json.loads(raw) if isinstance(raw, str) else dict(raw)
    if "private_key" in account:
        account["private_key"] = str(account["private_key"]).replace("\\\\n", "\n").replace("\\n", "\n")
    creds = service_account.Credentials.from_service_account_info(
        account,
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.readonly"],
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open(TEST_TITLE)
    if spreadsheet.title != TEST_TITLE:
        raise RuntimeError("Unexpected spreadsheet title; aborting")
    return spreadsheet

def numeric(value, digits=2):
    try:
        v = float(value)
        return round(v, digits) if math.isfinite(v) else ""
    except (TypeError, ValueError, OverflowError):
        return ""

def ratio_percent(value):
    v = numeric(value, 5)
    return numeric(v * 100) if v != "" else ""

def research(ticker, run_id, scanned_at):
    obj = yf.Ticker(ticker)
    # Daily history is used consistently for the price and technical calculations.
    hist = obj.history(period="15mo", interval="1d", auto_adjust=False)
    if hist is None or hist.empty or "Close" not in hist:
        raise ValueError(f"No daily price history returned for {ticker}")
    close = pd.to_numeric(hist["Close"], errors="coerce").dropna()
    if close.empty:
        raise ValueError(f"No valid closing prices returned for {ticker}")
    price = numeric(close.iloc[-1])
    as_of = str(close.index[-1].date())
    sma = {n: numeric(close.tail(n).mean()) if len(close) >= n else "" for n in (20, 50, 200)}
    vol = pd.to_numeric(hist.get("Volume", pd.Series(dtype=float)), errors="coerce").dropna()
    # Compare latest daily volume with preceding 20 completed sessions.
    rv = numeric(vol.iloc[-1] / vol.iloc[-21:-1].mean()) if len(vol) >= 21 and vol.iloc[-21:-1].mean() > 0 else ""
    year = close.tail(252)
    low, high = numeric(year.min()), numeric(year.max())
    try:
        info = obj.info or {}
    except Exception:
        info = {}
    try:
        calendar = obj.calendar or {}
        ed = calendar.get("Earnings Date") if isinstance(calendar, dict) else None
        if isinstance(ed, (list, tuple)):
            ed = ed[0] if ed else None
        earnings = ed.date().isoformat() if hasattr(ed, "date") else str(ed)[:10] if ed else ""
    except Exception:
        earnings = ""
    eligible = "YES" if 10 <= price <= 225 else "NO"
    above = [("YES" if price > sma[n] else "NO") if sma[n] != "" else "UNVERIFIED" for n in (20, 50, 200)]
    technical = all(x == "YES" for x in above) and rv != "" and rv >= 1.2
    classification = "TECHNICAL WATCH" if technical and eligible == "YES" else "RESEARCH / VERIFY"
    return [
        run_id, scanned_at, ticker, price, as_of, eligible,
        sma[20], sma[50], sma[200], *above, low, high, rv,
        earnings, "UNVERIFIED — third-party estimate" if earnings else "UNAVAILABLE",
        ratio_percent(info.get("revenueGrowth")), ratio_percent(info.get("operatingMargins")),
        numeric(info.get("forwardPE")), classification,
        "PARTIAL — earnings and fundamentals require independent verification",
        "Yahoo Finance via yfinance (daily bars)",
        "Storage test; not a BUY recommendation; no opportunity score assigned",
    ]

st.caption("Quotes are latest available daily closing prices, not live or premarket quotes. Earnings are not treated as company-confirmed.")
tickers_text = st.text_input("Tickers to research (comma-separated; maximum 5)", value="NVDA, VRT, AMD")
if st.button("Research stocks, write to test Sheet, and verify", type="primary"):
    symbols = list(dict.fromkeys(s.strip().upper() for s in tickers_text.split(",") if s.strip()))
    if not symbols or len(symbols) > 5 or any(not s.replace("-", "").replace(".", "").isalnum() for s in symbols):
        st.error("Enter 1–5 valid ticker symbols separated by commas.")
        st.stop()
    run_id = str(uuid.uuid4())
    scanned_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    rows, errors = [], []
    with st.spinner("Retrieving daily market data and calculating indicators..."):
        for symbol in symbols:
            try:
                rows.append(research(symbol, run_id, scanned_at))
            except Exception as exc:
                errors.append(f"{symbol}: {type(exc).__name__}: {exc}")
    for error in errors:
        st.warning(error)
    if not rows:
        st.error("No research rows were available. Nothing was written.")
        st.stop()
    st.subheader("Research rows prepared")
    st.dataframe(pd.DataFrame(rows, columns=HEADERS), use_container_width=True, hide_index=True)
    try:
        spreadsheet = connection()
        try:
            ws = spreadsheet.worksheet(TEST_TAB)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=TEST_TAB, rows=1000, cols=len(HEADERS))
        existing = ws.get_all_values()
        # Google Sheets may return empty-looking rows; check actual cell content.
        has_content = any(str(cell).strip() for row in existing for cell in row)
        if not has_content:
            ws.update(range_name="A1", values=[HEADERS], value_input_option="RAW")
            confirmed_header = ws.row_values(1)
            if confirmed_header != HEADERS:
                raise RuntimeError("Header initialization could not be verified. No research rows written.")
        elif ws.row_values(1) != HEADERS:
            actual_headers = ws.row_values(1)
            raise RuntimeError(
                "Research test tab has existing content with incompatible headers; no write attempted. "
                f"Found {len(actual_headers)} header cells; expected {len(HEADERS)}. "
                f"First five existing cells: {actual_headers[:5]!r}"
            )
        ws.append_rows(rows, value_input_option="RAW")
        stored = ws.get_all_values()
        matching = [r for r in stored[1:] if r and r[0] == run_id]
        if len(matching) != len(rows):
            raise RuntimeError(f"Read-back verification failed: expected {len(rows)} rows, found {len(matching)}. Inspect test tab before retrying.")
        # Google Sheets returns numeric values as strings. Compare string forms.
        for expected, actual in zip(rows, matching):
            if [str(x) for x in expected] != actual[:len(HEADERS)]:
                raise RuntimeError("Read-back content mismatch. Inspect the test tab before retrying.")
        st.success(f"SUCCESS — {len(rows)} stock-research rows written and read back correctly from {TEST_TAB}.")
        st.caption(f"Verified run ID: {run_id}")
    except Exception as exc:
        st.error(f"Storage test not confirmed: {type(exc).__name__}: {exc}")
        st.caption("The production spreadsheet was not accessed. Do not retry until any partial test writes are inspected.")
