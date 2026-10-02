import streamlit as st

from core.extract import extract_facts

st.set_page_config(page_title="ClearLegacy", layout="wide")

st.title("ClearLegacy")
st.write(
    "Help advisors identify potential inconsistencies "
    "between client intentions and beneficiary records."
)

st.caption("Prototype using fictional data. Findings require advisor review.")

st.subheader("Sample household")
st.write("Jordan Morgan recently remarried.")

left, right = st.columns(2)

with left:
    st.text_area(
        "Client planning summary",
        value=(
            "Jordan's current spouse is Casey Morgan. "
            "Jordan wants Casey to be the primary beneficiary "
            "of their retirement account."
        ),
        key="planning_summary",
    )

with right:
    st.text_area(
        "Account beneficiary record",
        value=(
            "Account: Retirement IRA\n"
            "Primary beneficiary: Taylor Morgan\n"
            "Relationship: Former spouse"
        ),
        key="beneficiary_record",
    )

if st.button("Analyze records", type="primary"):
    documents = [
        {
            "sourceId": "streamlit-planning-summary",
            "filename": "planning_summary.txt",
            "docType": "planning_summary",
            "sections": [{"location": "page 1", "text": st.session_state.planning_summary}],
        },
        {
            "sourceId": "streamlit-account-record",
            "filename": "account_record.txt",
            "docType": "account_records",
            "sections": [{"location": "page 1", "text": st.session_state.beneficiary_record}],
        },
    ]
    try:
        with st.spinner("Extracting evidence with Amazon Bedrock..."):
            planning_facts = extract_facts(documents[0])
            account_facts = extract_facts(documents[1])
        st.success("Bedrock extraction completed.")
        st.subheader("Extracted facts")
        st.json({"planning": planning_facts, "account": account_facts})
    except Exception as exc:
        st.error(f"Bedrock extraction failed: {exc}")