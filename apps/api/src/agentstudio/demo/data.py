"""Inputs for the demo runs. Every person, company and address here is fictional."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentstudio.templates.catalog import INVOICE, LEAD_MESSAGE, MEETING_NOTES, SUPPORT_TICKET


@dataclass(frozen=True, slots=True)
class Person:
    email: str
    name: str
    role: str
    admin: bool = False


PEOPLE = (
    Person("ava.martin@northwind.example", "Ava Martin", "owner", admin=True),
    Person("leo.chen@northwind.example", "Leo Chen", "editor"),
    Person("sam.rivera@northwind.example", "Sam Rivera", "editor"),
    Person("maya.patel@northwind.example", "Maya Patel", "viewer"),
)

WORKSPACE = (
    "Northwind Operations",
    "Support, finance, sales and people workflows for Northwind Cloud.",
)
SECOND_WORKSPACE = ("Leo's experiments", "Prototypes and flows in progress.")


@dataclass(frozen=True, slots=True)
class Scenario:
    template: str
    inputs: dict[str, Any]
    actor: str = "leo.chen@northwind.example"
    trigger: str = "manual"
    decision: str | None = None
    decider: str = "ava.martin@northwind.example"
    comment: str = ""
    days_ago: float = 3
    cancel: bool = False
    version: str = "published"
    extra: dict[str, Any] = field(default_factory=dict)


def ticket(subject: str, body: str, email: str) -> dict[str, Any]:
    return {"subject": subject, "body": body, "customer_email": email}


SUPPORT = (
    Scenario(
        "support-triage",
        ticket(
            "Charged twice for the March invoice", SUPPORT_TICKET, "dana.whitfield@globex.example"
        ),
        trigger="webhook",
        decision="approve",
        comment="Refund confirmed with finance. Sending.",
        days_ago=12.4,
    ),
    Scenario(
        "support-triage",
        ticket(
            "Dashboard down for our whole support team",
            "Since 9:10 this morning the dashboard is down for all of our agents and nothing loads. "
            "This is urgent: our production support queue is blocked and we are losing revenue. "
            "Please escalate immediately.\n\nOlivia Brown\nHooli",
            "olivia.brown@hooli.example",
        ),
        trigger="webhook",
        decision="approve",
        decider="sam.rivera@northwind.example",
        comment="On-call engineer paged; status page updated.",
        days_ago=10.6,
    ),
    Scenario(
        "support-triage",
        ticket(
            "How do I export the weekly report?",
            "Hello, quick question: how can I export the weekly report to CSV? Thanks, Tom",
            "tom.becker@brightside.example",
        ),
        days_ago=9.2,
    ),
    Scenario(
        "support-triage",
        ticket(
            "Locked out after enabling SSO",
            "Hi, after we switched on single sign-on yesterday, three of our agents cannot log in. "
            "They see an access denied error. Could you help us reset their access?\n\nThanks,\nMarco Rossi",
            "marco.rossi@initech.example",
        ),
        days_ago=8.3,
    ),
    Scenario(
        "support-triage",
        ticket(
            "Suggestion: dark mode",
            "It would be great to have a dark mode option for the agent workspace. No rush, just a "
            "suggestion from our night shift.\n\nLi Wei",
            "li.wei@umbrella.example",
        ),
        days_ago=7.5,
    ),
    Scenario(
        "support-triage",
        ticket(
            "Refund for unused seats",
            "We reduced our team from 40 to 32 agents last month. Can we get a refund for the 8 "
            "unused seats on our annual plan?\n\nAna Silva\nStark Logistics",
            "ana.silva@starklogistics.example",
        ),
        days_ago=6.2,
    ),
    Scenario(
        "support-triage",
        ticket(
            "API returning 500 errors",
            "Since this morning our integration gets HTTP 500 errors from the tickets API for about "
            "one in five requests. This is affecting several customers. Request id: 7f3a9c.\n\nJames Okafor",
            "james.okafor@waynefoods.example",
        ),
        decision="reject",
        comment="Engineering needs the request logs first. Escalating to the API team.",
        days_ago=4.4,
    ),
    Scenario(
        "support-triage",
        ticket(
            "Thanks for the quick help!",
            "Just wanted to say thanks, the report export works great now. Love the new filters!\n\nTom",
            "tom.becker@brightside.example",
        ),
        days_ago=2.1,
    ),
    Scenario(
        "support-triage",
        ticket(
            "Invoice is missing our PO number",
            "Hello, our April invoice does not show the purchase order number PO-55812, so our "
            "accounts payable team cannot process it. Could you reissue it?\n\nThanks,\nDana Whitfield",
            "dana.whitfield@globex.example",
        ),
        trigger="webhook",
        days_ago=0.4,
    ),
    Scenario(
        "support-triage",
        ticket(
            "Webhook deliveries failing since yesterday",
            "Our endpoint stopped receiving webhook deliveries yesterday afternoon. The delivery log "
            "shows timeouts. Can you check what changed on your side?\n\nOlivia Brown",
            "olivia.brown@hooli.example",
        ),
        days_ago=0.15,
    ),
)

CONTOSO = """CONTOSO CLOUD SERVICES
500 Market Street, Seattle WA 98101

INVOICE
Invoice Number: CCS-88412
Invoice Date: 1 April 2026
Due Date: 16 May 2026
Payment terms: Net 45

Description                        Qty    Unit price    Amount
Compute reserved instances           1      8,400.00   8,400.00
Managed database cluster             1      2,150.00   2,150.00
Premium support                      1      1,200.00   1,200.00

Subtotal                                              11,750.00
Sales tax (0%)                                             0.00
Total due (USD)                                       11,750.00"""

FABRIKAM = """FABRIKAM LOGISTICS
Hafenstrasse 12, 20457 Hamburg

INVOICE
Invoice Number: FL-2026-0311
Invoice Date: 11 March 2026
Due Date: 10 April 2026
Payment terms: Net 30

Description                        Qty    Unit price    Amount
Pallet freight Hamburg to Lyon      12        420.00   5,040.00
Customs handling                     1        360.00     360.00

Subtotal                                               5,400.00
VAT (20%)                                              1,080.00
Total due (EUR)                                        6,480.00"""

CATERING = """NORTHWIND CATERING CO
22 Rue des Halles, 75001 Paris

INVOICE
Invoice Number: NCC-1182
Invoice Date: 14 April 2026
Due Date: 29 April 2026
Payment terms: Net 15

Description                        Qty    Unit price    Amount
Team offsite lunch (45 people)      45         36.00   1,620.00
Coffee and pastries                 45          8.00     360.00

Subtotal                                               1,980.00
VAT (10%)                                                198.00
Total due (EUR)                                        2,178.00"""

TAILSPIN = """TAILSPIN SOFTWARE
88 Harbor Drive, San Diego CA 92101

INVOICE
Invoice Number: TS-4471
Invoice Date: 2 May 2026
Due Date: 1 June 2026
Payment terms: Net 30

Description                        Qty    Unit price    Amount
Analytics licences (annual)         40        240.00   9,600.00

Subtotal                                               9,600.00
Sales tax (8%)                                           768.00
Total due (USD)                                       10,468.00"""

SCANNED = """SCANNED DOCUMENT - page 1 of 2
[image too blurry to read]
... nvoice ... 2026 ... lease remit ...
[stamp] RECEIVED"""

INVOICES = (
    Scenario("invoice-extraction", {"invoice_text": INVOICE}, trigger="api", days_ago=11.3),
    Scenario("invoice-extraction", {"invoice_text": CONTOSO}, trigger="api", days_ago=9.6),
    Scenario(
        "invoice-extraction",
        {"invoice_text": FABRIKAM},
        trigger="api",
        decision="reject",
        comment="Bank details are still under review. Do not pay yet.",
        days_ago=7.1,
    ),
    Scenario(
        "invoice-extraction",
        {"invoice_text": CATERING},
        decision="approve",
        comment="Offsite catering, approved.",
        days_ago=5.3,
    ),
    Scenario("invoice-extraction", {"invoice_text": SCANNED}, trigger="api", days_ago=3.2),
    Scenario("invoice-extraction", {"invoice_text": TAILSPIN}, trigger="api", days_ago=0.3),
)

RESEARCH = (
    Scenario(
        "research-brief",
        {"topic": "Rolling out the new remote work policy", "audience": "People team leads"},
        actor="sam.rivera@northwind.example",
        days_ago=10.1,
    ),
    Scenario(
        "research-brief",
        {"topic": "Reducing support response times", "audience": "Support leadership"},
        days_ago=6.6,
    ),
    Scenario(
        "research-brief",
        {"topic": "Expanding the warehouse robotics pilot", "audience": "Operations"},
        actor="sam.rivera@northwind.example",
        days_ago=1.7,
    ),
)

LEADS = (
    Scenario(
        "lead-qualification",
        {
            "name": "Priya Raman",
            "email": "priya.raman@initech.example",
            "company": "Initech",
            "message": LEAD_MESSAGE,
        },
        trigger="api",
        days_ago=12.9,
    ),
    Scenario(
        "lead-qualification",
        {
            "name": "Tom Becker",
            "email": "tom.becker@brightside.example",
            "company": "Brightside Bakery",
            "message": "Just curious what your tool does. We are a small team and not ready to buy anything yet.",
        },
        trigger="api",
        days_ago=11.1,
    ),
    Scenario(
        "lead-qualification",
        {
            "name": "Sofia Gomez",
            "email": "sofia.gomez@massivedynamic.example",
            "company": "Massive Dynamic",
            "message": (
                "We need to replace our helpdesk before our contract ends this quarter. We have about "
                "300 agents across three regions and procurement has approved the budget. Can you "
                "send a quote for the Enterprise plan?"
            ),
        },
        trigger="api",
        days_ago=8.8,
    ),
    Scenario(
        "lead-qualification",
        {
            "name": "Kevin Liu",
            "email": "kevin.liu@gmail.com",
            "company": "Freelance",
            "message": "Hi, just exploring options for a client project. Do you have a free plan?",
        },
        trigger="api",
        days_ago=5.9,
    ),
    Scenario(
        "lead-qualification",
        {
            "name": "Hannah Schmidt",
            "email": "hannah.schmidt@piedpiper.example",
            "company": "Pied Piper",
            "message": "We are evaluating tools for our 12-person support team and would like a demo next month.",
        },
        trigger="api",
        days_ago=3.6,
    ),
    Scenario(
        "lead-qualification",
        {
            "name": "Raj Patel",
            "email": "raj.patel@soylent.example",
            "company": "Soylent Foods",
            "message": (
                "Our support team of 60 agents needs better triage. We have budget approved and want "
                "to roll out next month. Please send pricing."
            ),
        },
        trigger="api",
        days_ago=1.2,
    ),
)

STAFFING = """Sam: Let's go through Q4 support staffing. Ticket volume is up 14 percent on Q3.
Maya: Weekend billing questions are the biggest gap; they were 22 percent of weekend tickets.
Sam: We agreed to add a weekend on-call rotation for billing starting in November.
Leo: I'll draft the rotation schedule and share it with the team by Friday.
Maya: I will rewrite the three invoice help articles by next Wednesday.
Sam: Ava will approve the overtime budget for the rotation.
Leo: Risk: if hiring slips we may need contractors for December."""

REDESIGN = """Ava: Kickoff for the website redesign. The goal is a launch before the January pricing change.
Sam: Design has three concepts ready for review.
Leo: We decided to keep the current pricing page structure and only refresh the visuals.
Sam: I'll schedule the concept review with marketing for Tuesday.
Leo: I will audit the current page performance by end of week.
Ava: Maya will collect customer quotes for the new homepage by next month."""

VENDOR_REVIEW = """Ava: Quick review of Fabrikam Logistics after the invoice hold.
Sam: Their bank details changed twice in a month, which triggered the hold.
Ava: We agreed to keep payments on hold until finance verifies the new account by phone.
Sam: I'll call their finance contact to verify the account tomorrow.
Ava: Let me update the vendor risk register by Friday."""

MEETINGS = (
    Scenario(
        "meeting-actions",
        {"title": "Atlas v2 beta launch sync", "notes": MEETING_NOTES},
        actor="ava.martin@northwind.example",
        days_ago=9.9,
    ),
    Scenario(
        "meeting-actions",
        {"title": "Q4 support staffing review", "notes": STAFFING},
        actor="sam.rivera@northwind.example",
        days_ago=6.9,
    ),
    Scenario(
        "meeting-actions",
        {"title": "Website redesign kickoff", "notes": REDESIGN},
        days_ago=4.8,
    ),
    Scenario(
        "meeting-actions",
        {"title": "Vendor review: Fabrikam Logistics", "notes": VENDOR_REVIEW},
        actor="ava.martin@northwind.example",
        days_ago=2.6,
    ),
)

QUESTIONS = (
    "How many vacation days do full-time employees get each year?",
    "How long is parental leave for primary caregivers?",
    "Can I work from another country for a few weeks?",
    "How much can I claim for home office equipment?",
    "What is the daily meal allowance when travelling in Europe?",
    "How many unused vacation days can I carry over?",
)

POLICY = tuple(
    Scenario(
        "policy-assistant",
        {"question": question},
        actor="maya.patel@northwind.example" if index % 2 else "leo.chen@northwind.example",
        trigger="api",
        days_ago=13.0 - index * 2.1,
    )
    for index, question in enumerate(QUESTIONS)
)

# A run cancelled while it waited for review, and a run of a flow's work-in-progress draft.
EXTRA = (
    Scenario(
        "support-triage",
        ticket(
            "Please cancel our renewal",
            "We are consolidating tools and would like to cancel the renewal of our sandbox "
            "workspace at the end of the month. Please confirm the final invoice.\n\nOlivia Brown",
            "olivia.brown@hooli.example",
        ),
        cancel=True,
        days_ago=5.6,
        extra={"note": "cancelled while waiting"},
    ),
    Scenario(
        "research-brief",
        {"topic": "Hybrid work and office space", "audience": "Facilities"},
        version="draft",
        days_ago=0.9,
    ),
)

SCENARIOS: tuple[Scenario, ...] = (
    *SUPPORT,
    *INVOICES,
    *RESEARCH,
    *LEADS,
    *MEETINGS,
    *POLICY,
    *EXTRA,
)
