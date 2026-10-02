"""Unit tests for core.validation.validate_facts. No AWS access needed."""

from pathlib import Path

from core.extract import load_document
from core.validation import validate_facts

FIXTURES = Path(__file__).parent / "fixtures"

DOCUMENT = {
    "sourceId": "johnson-will",
    "filename": "johnson_will.txt",
    "docType": "will",
    "sections": [
        {"location": "page 1", "text": "I give the residue of my estate\nin equal shares to my children,\nEmily Johnson, David Johnson and Sarah Johnson."},
        {"location": "page 2", "text": "I nominate and appoint my brother, Thomas Johnson, as Executor of this Will."},
    ],
}


def _fact(field, value, quote, location):
    return {"field": field, "value": value, "location": location, "quote": quote,
            "accountRef": None, "tier": None, "allocation": None, "relationship": None, "asOf": None}


def _facts(*facts):
    return {"sourceId": "johnson-will", "docType": "will", "facts": list(facts), "warnings": []}


def test_existing_quote_is_kept():
    # Different case and whitespace than the source still verifies.
    fact = _fact("residuary_beneficiary", "Emily Johnson", "in equal shares to my children, EMILY Johnson", "page 1")
    out = validate_facts(_facts(fact), DOCUMENT)
    assert out["facts"] == [fact]
    assert out["warnings"] == [] and out["excludedFacts"] == []


def test_made_up_quote_is_dropped_with_warning():
    fake = _fact("residuary_beneficiary", "Linda Johnson", "I leave everything to my wife Linda Johnson", "page 1")
    real = _fact("executor", "Thomas Johnson", "my brother, Thomas Johnson, as Executor", "page 2")
    out = validate_facts(_facts(fake, real), DOCUMENT)
    assert [f["value"] for f in out["facts"]] == ["Thomas Johnson"]
    assert len(out["warnings"]) == 1
    assert isinstance(out["warnings"][0], str) and "Linda Johnson" in out["warnings"][0]
    assert out["excludedFacts"][0]["value"] == "Linda Johnson"


def test_wrong_location_is_corrected():
    fact = _fact("executor", "Thomas Johnson", "appoint my brother, Thomas Johnson", "page 1")
    out = validate_facts(_facts(fact), DOCUMENT)
    assert out["facts"][0]["location"] == "page 2"
    assert out["warnings"] == []


def test_input_is_not_mutated():
    fact = _fact("executor", "Thomas Johnson", "appoint my brother, Thomas Johnson", "page 1")
    facts = _facts(fact)
    validate_facts(facts, DOCUMENT)
    assert facts["facts"][0]["location"] == "page 1"


def test_ellipsis_quote_kept_only_if_fragments_verify_in_order():
    ok = _fact("residuary_beneficiary", "Emily Johnson", "I give the residue of my estate... to my children, Emily Johnson", "page 1")
    reordered = _fact("residuary_beneficiary", "David Johnson", "to my children… I give the residue", "page 1")
    invented = _fact("residuary_beneficiary", "Sarah Johnson", "I give the residue ... to my wife Linda", "page 1")
    out = validate_facts(_facts(ok, reordered, invented), DOCUMENT)
    assert [f["value"] for f in out["facts"]] == ["Emily Johnson"]
    assert len(out["warnings"]) == 2


def test_quotes_verify_against_real_pdf_text():
    # reportlab/pypdf reflow lines; normalization must still match.
    document = load_document(FIXTURES / "pdf" / "johnson_trust.pdf", "trust")
    assert [s["location"] for s in document["sections"]] == ["page 1", "page 2"]
    fact = _fact("trust_owned_account", "DEMO-JOHNSON-4471",
                 "Brokerage account DEMO-JOHNSON-4471 shall be held by and titled in the name of the Trust.", "page 2")
    out = validate_facts(_facts(fact), document)
    assert out["facts"][0]["location"] == "page 1"
