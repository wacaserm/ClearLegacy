"""'Who gets what': one row per account comparing what documents intend with what is on file."""

from ui.excerpt import accounts_in, short_title
from ui.html import beneficiary_text, esc, priority_key, render

STATUS = {
    "mismatch": ("Mismatch", "critical"),
    "review": ("Needs review", "review"),
    "none": ("No issue found", "clear"),
}


def account_status(account_id, findings):
    """Status and the findings that mention this account."""
    related = [f for f in findings if account_id in accounts_in(f)]
    priorities = {priority_key(f.get("priority")) for f in related}
    if priorities & {"critical", "high"}:
        return "mismatch", related
    if related:
        return "review", related
    return "none", related


def _intended_html(related, names):
    """Document quotes from the findings for this account; never guessed."""
    quotes = []
    for finding in related:
        for item in finding.get("evidence", []) or []:
            if isinstance(item, dict) and item.get("sourceType") == "document" and item.get("quote"):
                source = item.get("filename") or names.get(item.get("sourceId")) or "Document"
                entry = (short_title(item["quote"], 110), source)
                if entry not in quotes:
                    quotes.append(entry)
    if not quotes:
        return '<span class="sub" style="display:inline">Not stated in documents</span>'
    return "<br>".join(f'&ldquo;{esc(q)}&rdquo;<span class="sub">{esc(s)}</span>' for q, s in quotes[:2])


def render_overview(accounts, findings, names=None):
    if not accounts:
        return
    names = names or {}
    rows = []
    for account in accounts:
        account_id = account.get("accountId", "Account")
        status, related = account_status(account_id, findings)
        label, tone = STATUS[status]
        kind = " · ".join(v for v in (account.get("accountType"), account.get("designationType")) if v)
        primary = account.get("primaryBeneficiaries") or account.get("todBeneficiaries") or account.get("beneficiaries")
        contingent = account.get("contingentBeneficiaries")
        on_file = beneficiary_text(primary)
        if contingent:
            on_file += '<span class="sub">Contingent</span>' + beneficiary_text(contingent)
        rows.append(
            "<tr>"
            f'<td><b>{esc(account_id)}</b><span class="sub">{esc(kind)}</span></td>'
            f"<td>{_intended_html(related, names)}</td>"
            f"<td>{on_file}</td>"
            f'<td><span class="cl-pill {tone}">{esc(label)}</span></td>'
            "</tr>"
        )
    render('<p class="cl-section" style="margin-top:24px">Who gets what</p>'
           '<div class="cl-table-wrap"><table class="cl-table"><thead><tr>'
           "<th>Account</th><th>Documents intend</th><th>On file</th><th>Status</th>"
           "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
           '<p class="cl-small" style="margin-top:6px">"No issue found" means the rules found no difference '
           "within the documents and records supplied.</p>")
