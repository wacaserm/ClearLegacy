"""Unit tests for validate_facts. No AWS access needed."""

from pathlib import Path

from core.extract import read_pdf, validate_facts

FIXTURES = Path(__file__).parent / "fixtures"

PAGES = [
    {"page": 1, "text": "I give the residue of my estate,\nin equal shares to my children,\nEmily Johnson, David Johnson and Sarah Johnson."},
    {"page": 2, "text": "I nominate and appoint my brother, Thomas Johnson, as Executor of this Will."},
]


def _facts(people=(), assets=(), date=None, state=None):
    return {
        "docType": "will",
        "dateSigned": date or {"value": None, "page": None, "quote": None},
        "governingState": state or {"value": None, "page": None, "quote": None},
        "people": list(people),
        "assets": list(assets),
    }


def _person(name, quote, page, role="beneficiary"):
    return {"name": name, "relationship": "", "role": role, "share": None, "page": page, "quote": quote}


def test_existing_quote_is_kept():
    # Different case and whitespace than the source still verifies.
    item = _person("Emily Johnson", "in equal shares to my children, EMILY Johnson", 1)
    out = validate_facts(_facts(people=[item]), PAGES)
    assert out["people"] == [item]
    assert out["dropped"] == []


def test_made_up_quote_is_dropped():
    fake = _person("Linda Johnson", "I leave everything to my wife Linda Johnson", 1)
    real = _person("Thomas Johnson", "my brother, Thomas Johnson, as Executor", 2, role="executor")
    out = validate_facts(_facts(people=[fake, real]), PAGES)
    assert [p["name"] for p in out["people"]] == ["Thomas Johnson"]
    assert len(out["dropped"]) == 1
    assert out["dropped"][0]["field"] == "people"
    assert out["dropped"][0]["item"]["name"] == "Linda Johnson"


def test_wrong_page_is_corrected():
    item = _person("Thomas Johnson", "appoint my brother, Thomas Johnson", 1, role="executor")
    out = validate_facts(_facts(people=[item]), PAGES)
    assert out["people"][0]["page"] == 2
    assert out["dropped"] == []


def test_unverified_scalar_is_nulled_and_input_untouched():
    date = {"value": "2019-03-14", "page": 2, "quote": "signed this Will on March 14, 2019"}
    facts = _facts(date=date)
    out = validate_facts(facts, PAGES)
    assert out["dateSigned"] == {"value": None, "page": None, "quote": None}
    assert out["dropped"][0]["field"] == "dateSigned"
    assert facts["dateSigned"]["value"] == "2019-03-14"  # original not mutated


def test_quotes_verify_against_real_pdf_text():
    # reportlab/pypdf reflow lines; normalization must still match.
    pages = read_pdf(FIXTURES / "pdf" / "johnson_trust.pdf")
    asset = {
        "description": "Brokerage account ending 4471",
        "disposition": "Held by and titled in the name of the Trust",
        "page": 2,
        "quote": "The brokerage account ending 4471 shall be held by and titled in the name of the Trust.",
    }
    out = validate_facts(_facts(assets=[asset]), pages)
    assert out["assets"][0]["page"] == 1


def test_ellipsis_quote_kept_only_if_fragments_verify_in_order():
    ok = _person("Emily Johnson", "I give the residue of my estate... to my children, Emily Johnson", 1)
    reordered = _person("David Johnson", "to my children… I give the residue", 1)
    invented = _person("Sarah Johnson", "I give the residue ... to my wife Linda", 1)
    out = validate_facts(_facts(people=[ok, reordered, invented]), PAGES)
    assert [p["name"] for p in out["people"]] == ["Emily Johnson"]
    assert len(out["dropped"]) == 2
