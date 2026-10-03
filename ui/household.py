import streamlit as st

from ui import compat
from ui.html import STATUS_PILLS, beneficiary_text, esc, render

# compat.badge color for each status pill (label always shown).
_BADGE_COLORS = {"neutral": "gray", "brand": "blue", "high": "orange", "review": "blue", "clear": "green", "critical": "red"}

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}


def render_household(client, status, accounts=None):
    name = client.get("name") or client.get("clientName") or "Household"
    label, tone = STATUS_PILLS.get(status, STATUS_PILLS["not_analyzed"])
    title_column, status_column = st.columns([5, 1.4], vertical_alignment="center")
    with title_column:
        render('<p class="cl-label" style="margin:0 0 4px">Household</p>'
               f'<div class="cl-title cl-serif" role="heading" aria-level="1">{esc(name)}</div>')
    with status_column:
        compat.badge(label, color=_BADGE_COLORS.get(tone, "gray"))

    facts = []
    state = client.get("state")
    if state:
        facts.append(("Residence", US_STATES.get(str(state).upper(), state)))
    if client.get("currentSpouse"):
        facts.append(("Spouse", client["currentSpouse"]))
    if client.get("trustName"):
        facts.append(("Trust", client["trustName"]))
    if accounts:
        facts.append(("Accounts", str(len(accounts))))
        snapshots = sorted({a.get("snapshotDate") for a in accounts if a.get("snapshotDate")})
        if snapshots:
            facts.append(("Records as of", snapshots[-1]))
    if facts:
        render('<div class="cl-meta">' + "".join(
            f'<span>{esc(k)} <b class="cl-num">{esc(v)}</b></span>' for k, v in facts) + "</div>")


def _contingent_cell(account):
    rows = account.get("contingentBeneficiaries")
    if rows:
        return beneficiary_text(rows)
    status = account.get("contingentDataStatus")
    readable = {
        "none_listed_in_snapshot": "None listed in snapshot",
        "not_supplied": "Not supplied",
    }.get(status, "None listed")
    return f'<span class="sub" style="display:inline">{esc(readable)}</span>'


def render_account_details(accounts):
    render('<p class="cl-label" style="margin-top:24px">Accounts on file</p>')
    if accounts:
        snapshots = sorted({a.get("snapshotDate") for a in accounts if a.get("snapshotDate")})
        as_of = f", as of {snapshots[-1]}" if snapshots else ""
        render(f'<p class="cl-small" style="margin:-2px 0 8px">From the firm\'s account records (demo data){esc(as_of)}. '
               "Estate documents are read only when you click Analyze.</p>")
    if not accounts:
        render('<div class="cl-notice">No account records are available from the configured store. '
               'Account details are never inferred from document filenames.</div>')
        return
    rows = []
    for account in accounts:
        primary = account.get("primaryBeneficiaries") or account.get("todBeneficiaries") or account.get("beneficiaries")
        designation = account.get("designationType")
        kind = " · ".join(v for v in (account.get("accountType") or account.get("type"), designation) if v)
        updated = account.get("designationUpdatedDate") or "—"
        snapshot = account.get("snapshotDate")
        rows.append(
            "<tr>"
            f'<td><b>{esc(account.get("accountId", "Account"))}</b><span class="sub">{esc(kind)}</span></td>'
            f'<td>{esc(account.get("registration") or "—")}</td>'
            f"<td>{beneficiary_text(primary)}</td>"
            f"<td>{_contingent_cell(account)}</td>"
            f'<td class="num">{esc(updated)}'
            + (f'<span class="sub">Snapshot {esc(snapshot)}</span>' if snapshot else "")
            + "</td></tr>"
        )
    render(
        '<div class="cl-table-wrap"><table class="cl-table"><thead><tr>'
        "<th>Account</th><th>Registration</th><th>Primary beneficiaries</th><th>Contingent</th><th>Designation updated</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )
