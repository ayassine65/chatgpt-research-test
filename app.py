import json
from datetime import datetime, timezone

import gspread
import streamlit as st
from google.oauth2 import service_account

st.set_page_config(page_title="Research Storage Test", page_icon="🧪")
st.title("ChatGPT Research — Isolated Storage Test")
st.info("This test connects only to the test spreadsheet. It does not connect to the Wealth Command Center production spreadsheet.")

TEST_TITLE = "ChatGPT_Research_Integration_Test"
TEST_TAB = "CHATGPT_RESEARCH_TEST"
HEADERS = ["Scan Date", "Ticker", "Price", "Status", "Source"]

if st.button("Run one-time write/read test", type="primary"):
    try:
        raw = st.secrets["gcp_service_account_json"]
        account = json.loads(raw) if isinstance(raw, str) else dict(raw)
        
        # Normalize escaped newlines in the service-account private key.
        if "private_key" in account:
            account["private_key"] = (
                str(account["private_key"])
                .replace("\\\\n", "\n")
                .replace("\\n", "\n")
            )
        
        creds = service_account.Credentials.from_service_account_info(
            account,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive.readonly",
            ],
        )
        client = gspread.authorize(creds)
        sheet = client.open(TEST_TITLE)
        if sheet.title != TEST_TITLE:
            raise RuntimeError("Unexpected spreadsheet; test aborted")
        try:
            ws = sheet.worksheet(TEST_TAB)
        except gspread.WorksheetNotFound:
            ws = sheet.add_worksheet(title=TEST_TAB, rows=100, cols=5)
        existing = ws.get_all_values()
        if existing:
            if existing[0] != HEADERS:
                raise RuntimeError("Existing test tab has different headers; no changes made")
            if len(existing) > 1:
                st.warning("Test data already exists. No duplicate record was written.")
                st.dataframe(existing[1:], use_container_width=True)
                st.stop()
        else:
            ws.update(range_name="A1:E1", values=[HEADERS])
        record = [datetime.now(timezone.utc).date().isoformat(), "TEST", "", "TEST ONLY", "Integration test"]
        ws.append_row(record, value_input_option="RAW")
        actual = ws.row_values(2)
        if actual != record:
            raise RuntimeError(f"Read-back mismatch: {actual!r}")
        st.success("SUCCESS — test record written and read back correctly")
        st.dataframe([dict(zip(HEADERS, actual))], use_container_width=True)
    except Exception as exc:
        st.error(f"Test did not complete: {type(exc).__name__}: {exc}")
        st.caption("No production spreadsheet changes were attempted.")
