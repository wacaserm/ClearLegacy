import streamlit as st

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
    st.info("Interface ready. Next step: connect Amazon Bedrock.")