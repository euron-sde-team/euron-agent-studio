from agentstudio.providers.offline import extract
from agentstudio.providers.offline.classify import candidate_labels, classify, confidence
from agentstudio.providers.offline.prompt import parse_blocks, parse_request, sentences
from agentstudio.providers.offline.tokens import count_request, count_tokens
from tests.unit.offline_samples import INVOICE, OUTAGE, TICKET


def test_prompts_split_into_instruction_fields_and_sections() -> None:
    text = (
        "Classify this ticket.\n\nSubject: Refund\nCustomer: dana@globex.example\n\n"
        "Ticket:\nLine one.\nBill To:\nAcme\n\nHelp center articles:\n[1] Refunds\nText."
    )
    instruction, sections, fields = parse_blocks(text)
    assert instruction == "Classify this ticket."
    assert fields["subject"] == "Refund"
    assert sections["ticket"] == "Line one.\nBill To:\nAcme"
    assert sections["help center articles"].startswith("[1] Refunds")


def test_long_instructions_with_colons_are_not_fields() -> None:
    instruction, _, fields = parse_blocks("Classify the sentiment of this review as one of: a, b.")
    assert instruction.startswith("Classify")
    assert fields == {}


def test_tool_results_are_paired_with_their_calls() -> None:
    prompt = parse_request(
        [
            {"role": "user", "content": "Price 3 seats"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "calc", "arguments": '{"expression": "3 * 5"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": '{"result": 15}'},
        ]
    )
    assert prompt.tool_results[0].name == "calc"
    assert prompt.tool_results[0].content == {"result": 15}
    assert prompt.calls_made == [("calc", '{"expression": "3 * 5"}')]


def test_sentences_drop_greetings_signatures_and_speakers() -> None:
    found = sentences(TICKET)
    assert found[0].startswith("I was charged twice")
    assert "Dana Whitfield" not in " ".join(found)
    assert sentences("Ava: We agreed to ship. Thanks.")[0] == "We agreed to ship."


def test_classification_uses_lexicons_scales_and_defaults() -> None:
    labels = ["billing", "technical", "account", "feature_request", "other"]
    assert classify(TICKET, labels) == "billing"
    assert classify(OUTAGE, labels) == "technical"
    assert classify("Hello, quick note.", labels) == "other"
    priorities = ["low", "normal", "high", "urgent"]
    assert classify(TICKET, priorities) == "high"
    assert classify(OUTAGE, priorities) == "urgent"
    assert classify("A small typo on the pricing page, no rush.", priorities) == "low"
    assert classify("How do I export a report?", priorities) == "normal"
    assert classify(OUTAGE, ["Low", "Medium", "Critical"]) == "Critical"
    assert classify(TICKET, ["positive", "neutral", "negative"]) == "negative"
    assert (
        classify("The support team was fantastic. Love it!", ["positive", "neutral", "negative"])
        == "positive"
    )
    assert 0.5 <= confidence(TICKET, labels) <= 0.98


def test_candidate_labels_are_read_from_free_text() -> None:
    assert candidate_labels("classify as one of: billing, technical or account.") == [
        "billing",
        "technical",
        "account",
    ]
    assert candidate_labels("no options here") == []


def test_invoice_values_are_extracted() -> None:
    assert extract.invoice_number(INVOICE, {"invoice number": "AOS-2026-0417"}) == "AOS-2026-0417"
    assert extract.invoice_number("Invoice #INV-99812 issued today", {}) == "INV-99812"
    assert extract.amount_near(INVOICE, ["subtotal"]) == 3527.0
    assert extract.amount_near(INVOICE, ["vat"]) == 705.4
    assert extract.amount_near(INVOICE, ["total due", "total"]) == 4232.4
    assert extract.currency(INVOICE) == "GBP"
    assert extract.currency("Total: \N{EURO SIGN}120.00") == "EUR"
    assert extract.payment_terms(INVOICE) == "Net 30"
    assert extract.vendor_name(INVOICE, {}) == "Acme Office Supplies Ltd"
    items = extract.line_items(INVOICE)
    assert [item["description"] for item in items] == [
        "Ergonomic office chair",
        "Standing desk (1.6m)",
        "Monitor arm, dual",
    ]
    assert items[1] == {
        "description": "Standing desk (1.6m)",
        "quantity": 4,
        "unit_price": 389.0,
        "amount": 1556.0,
    }


def test_dates_in_every_common_format() -> None:
    assert extract.dates("2026-03-04")[0][1] == "2026-03-04"
    assert extract.dates("on 3 March 2026")[0][1] == "2026-03-03"
    assert extract.dates("by Sept 9th, 2026")[0][1] == "2026-09-09"
    assert extract.dates("due 25/12/2026")[0][1] == "2026-12-25"
    assert extract.dates("due 04/05/2026")[0][1] == "2026-04-05"
    assert extract.date_near(INVOICE, ["due date"]) == "2026-04-02"
    assert extract.date_near("Payment due Friday please", ["due"]) == "Friday"


def test_contacts_names_companies_and_quantities() -> None:
    assert extract.emails("write to a.b@x.example or a.b@x.example") == ["a.b@x.example"]
    assert extract.domain_of("contact priya@initech.example") == "initech.example"
    assert extract.domain_of("see https://www.globex.example/about") == "globex.example"
    assert extract.person_name(TICKET, {}) == "Dana Whitfield"
    assert (
        extract.person_name("", {"customer": "dana.whitfield@globex.example"}) == "Dana Whitfield"
    )
    assert extract.company_name(TICKET, {}) == "Globex Corporation"
    assert extract.company_name("", {"company": "Initech"}) == "Initech"
    assert extract.quantity("We have 480 employees and about 120 agents", ["seats"]) == 120
    assert extract.quantity("We have 480 employees", ["headcount"]) == 480
    assert extract.lookup_field({"invoice date": "3 March 2026"}, "invoice_date") == "3 March 2026"
    assert extract.lookup_field({"name": "x"}, "invoice_date") is None


def test_token_estimates_are_stable() -> None:
    assert count_tokens("") == 0
    assert count_tokens("Hello world") == 2
    assert count_tokens("internationalization") == 4
    assert count_tokens("2026-03-04") == 6
    assert count_request([{"role": "user", "content": "Hello world"}], None) == 9
