"""The template gallery.

Each template is a complete, valid flow plus what it needs to run out of the box: sample
inputs for the run dialog and the knowledge bases it searches (shipped as Markdown documents
under `templates/knowledge/`). Knowledge nodes name their knowledge base with a placeholder
(`kb:<name>`) that is bound to a real knowledge base of the workspace when the template is
installed. HTTP nodes call the built-in sandbox API, so every template runs offline.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from typing import Any

SANDBOX = "https://sandbox.agentstudio.test"
KB_PLACEHOLDER = "kb:"


@dataclass(frozen=True, slots=True)
class KnowledgeSpec:
    name: str
    slug: str
    description: str


@dataclass(frozen=True, slots=True)
class Template:
    slug: str
    name: str
    description: str
    category: str
    tags: tuple[str, ...]
    sample: dict[str, Any]
    graph: dict[str, Any]
    knowledge: tuple[KnowledgeSpec, ...] = field(default_factory=tuple)


HELP_CENTER = KnowledgeSpec(
    "Help center", "help-center", "Customer-facing articles: billing, access, troubleshooting."
)
PRODUCT_HANDBOOK = KnowledgeSpec(
    "Product handbook", "product-handbook", "Plans, pricing, features, security, onboarding."
)
EMPLOYEE_HANDBOOK = KnowledgeSpec(
    "Employee handbook", "employee-handbook", "Time off, leave, remote work, expenses, security."
)
RESEARCH_LIBRARY = KnowledgeSpec(
    "Research library", "research-library", "Surveys, pilot retrospectives and operations reviews."
)


def node(
    node_id: str,
    node_type: str,
    x: float,
    y: float,
    *,
    label: str = "",
    settings: dict[str, Any] | None = None,
    **config: Any,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "position": {"x": x, "y": y},
        "label": label,
        "config": config,
        "settings": settings or {},
    }


def edge(
    source: str, target: str, source_handle: str = "out", target_handle: str = "in"
) -> dict[str, Any]:
    return {
        "id": f"e_{source}_{source_handle}_{target}_{target_handle}",
        "source": source,
        "source_handle": source_handle,
        "target": target,
        "target_handle": target_handle,
    }


def tool(tool_id: str, agent_id: str) -> dict[str, Any]:
    return edge(tool_id, agent_id, "tool", "tools")


def kb(spec: KnowledgeSpec) -> str:
    return KB_PLACEHOLDER + spec.name


def graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "nodes": nodes,
        "edges": edges,
        "viewport": {"x": 40, "y": 60, "zoom": 0.8},
    }


def field_(name: str, kind: str = "string", description: str = "", **extra: Any) -> dict[str, Any]:
    return {"name": name, "type": kind, "description": description, **extra}


RETRY = {"retries": 2, "retry_backoff_s": 1.0}

# --------------------------------------------------------------------------------------
# Support ticket triage with approval
# --------------------------------------------------------------------------------------

SUPPORT_TICKET = """Hi team,

I was charged twice for our March invoice (INV-2041) - $1,240.00 appears two times on our card statement. This is the second time this has happened and our finance team is asking questions. Please refund the duplicate charge as soon as possible.

Thanks,
Dana Whitfield
Globex Corporation"""

SUPPORT_TRIAGE = Template(
    slug="support-triage",
    name="Support ticket triage with approval",
    description=(
        "Classifies a ticket, looks the customer up in the CRM, searches the help center and "
        "drafts a reply. Urgent tickets and Enterprise customers wait for a human approval "
        "before the reply goes out."
    ),
    category="Customer support",
    tags=("support", "approval", "knowledge"),
    knowledge=(HELP_CENTER,),
    sample={
        "subject": "Charged twice for the March invoice",
        "body": SUPPORT_TICKET,
        "customer_email": "dana.whitfield@globex.example",
    },
    graph=graph(
        [
            node(
                "start",
                "start",
                0,
                220,
                inputs=[
                    field_("subject", description="The ticket subject line."),
                    field_("body", description="The customer's message."),
                    field_("customer_email", description="Who wrote in."),
                ],
            ),
            node(
                "about",
                "note",
                0,
                0,
                text=(
                    "Classify and look up the customer in parallel, then search the help "
                    "center and draft a reply. High-priority tickets and Enterprise customers "
                    "go to a reviewer; everything else is answered automatically."
                ),
                color="blue",
            ),
            node(
                "classify",
                "llm",
                300,
                120,
                label="Classify ticket",
                settings={**RETRY, "cache_ttl_s": 3600},
                model="offline",
                temperature=0,
                output_mode="json",
                system=(
                    "You triage support tickets for Northwind Cloud, a B2B software platform. "
                    "Decide which team owns the ticket, how urgent it is and how the customer feels."
                ),
                prompt=(
                    "Classify this support ticket.\n\nSubject: {{inputs.subject}}\n"
                    "Customer: {{inputs.customer_email}}\n\nTicket:\n{{inputs.body}}"
                ),
                json_fields=[
                    field_(
                        "category",
                        description="The team that should own the ticket.",
                        enum=["billing", "technical", "account", "feature_request", "other"],
                    ),
                    field_("priority", enum=["low", "normal", "high", "urgent"]),
                    field_("sentiment", enum=["positive", "neutral", "negative"]),
                    field_("summary", description="One sentence describing the problem."),
                ],
            ),
            node(
                "lookup_customer",
                "http",
                300,
                340,
                label="Look up customer",
                settings=RETRY,
                method="GET",
                url=f"{SANDBOX}/crm/contacts",
                query=[{"key": "email", "value": "{{inputs.customer_email}}"}],
                expect="json",
                fail_on_status=False,
            ),
            node(
                "search_help",
                "knowledge",
                600,
                120,
                label="Search help center",
                knowledge_base_id=kb(HELP_CENTER),
                query="{{inputs.subject}} {{classify.json.summary}}",
                top_k=3,
            ),
            node(
                "draft_reply",
                "llm",
                900,
                220,
                label="Draft reply",
                settings=RETRY,
                model="offline",
                temperature=0.3,
                max_tokens=600,
                system=(
                    "You are a support agent at Northwind Cloud. Write concise, friendly replies "
                    "in plain text. Use only the help center articles for policy details and "
                    "never promise anything they do not cover. Sign off as Northwind Support."
                ),
                prompt=(
                    "Draft a reply to this ticket.\n\n"
                    "Customer: {{lookup_customer.json.name}} ({{lookup_customer.json.company}}, "
                    "{{lookup_customer.json.plan}} plan)\nSubject: {{inputs.subject}}\n"
                    "Category: {{classify.json.category}}\nPriority: {{classify.json.priority}}\n\n"
                    "Ticket:\n{{inputs.body}}\n\nHelp center articles:\n{{search_help.context}}"
                ),
            ),
            node(
                "needs_review",
                "condition",
                1200,
                220,
                label="Needs a reviewer?",
                routes=[
                    {
                        "id": "review",
                        "label": "Needs review",
                        "match": "any",
                        "rules": [
                            {
                                "left": "{{classify.json.priority}}",
                                "operator": "in_list",
                                "right": "high, urgent",
                            },
                            {
                                "left": "{{lookup_customer.json.plan}}",
                                "operator": "equals",
                                "right": "enterprise",
                            },
                        ],
                    }
                ],
            ),
            node(
                "approve",
                "approval",
                1500,
                120,
                label="Review the reply",
                title="Review reply: {{inputs.subject}}",
                message="{{draft_reply.text}}",
                expires_after_hours=48,
            ),
            node(
                "sent",
                "output",
                1800,
                40,
                label="Reply approved",
                fields=[
                    {"name": "status", "value": "sent"},
                    {"name": "reply", "value": "{{draft_reply.text}}"},
                    {"name": "category", "value": "{{classify.json.category}}"},
                    {"name": "priority", "value": "{{classify.json.priority}}"},
                    {"name": "reviewer_note", "value": "{{approve.comment}}"},
                ],
            ),
            node(
                "escalated",
                "output",
                1800,
                220,
                label="Escalated",
                fields=[
                    {"name": "status", "value": "escalated"},
                    {"name": "category", "value": "{{classify.json.category}}"},
                    {"name": "priority", "value": "{{classify.json.priority}}"},
                    {"name": "reviewer_note", "value": "{{approve.comment}}"},
                ],
            ),
            node(
                "auto_reply",
                "output",
                1500,
                360,
                label="Auto-replied",
                fields=[
                    {"name": "status", "value": "auto-replied"},
                    {"name": "reply", "value": "{{draft_reply.text}}"},
                    {"name": "category", "value": "{{classify.json.category}}"},
                    {"name": "priority", "value": "{{classify.json.priority}}"},
                ],
            ),
        ],
        [
            edge("start", "classify"),
            edge("start", "lookup_customer"),
            edge("classify", "search_help"),
            edge("search_help", "draft_reply"),
            edge("lookup_customer", "draft_reply"),
            edge("draft_reply", "needs_review"),
            edge("needs_review", "approve", "route_review"),
            edge("needs_review", "auto_reply", "else"),
            edge("approve", "sent", "approved"),
            edge("approve", "escalated", "rejected"),
        ],
    ),
)

# --------------------------------------------------------------------------------------
# Invoice data extraction
# --------------------------------------------------------------------------------------

INVOICE = """ACME OFFICE SUPPLIES LTD
14 Harbour Road, Bristol BS1 5TT
billing@acme-supplies.example

INVOICE
Invoice Number: AOS-2026-0417
Invoice Date: 3 March 2026
Due Date: 2 April 2026
Payment terms: Net 30

Bill To:
Northwind Robotics
Accounts Payable

Description                        Qty    Unit price    Amount
Ergonomic office chair               6        249.00   1,494.00
Standing desk (1.6m)                 4        389.00   1,556.00
Monitor arm, dual                    6         79.50     477.00

Subtotal                                               3,527.00
VAT (20%)                                                705.40
Total due (GBP)                                        4,232.40"""

INVOICE_EXTRACTION = Template(
    slug="invoice-extraction",
    name="Invoice data extraction",
    description=(
        "Extracts vendor, dates, totals and line items from an invoice, checks the arithmetic, "
        "verifies the vendor in the ERP and shapes a posting record. Invoices over the vendor's "
        "approval limit, or that do not add up, go to finance for review."
    ),
    category="Finance",
    tags=("finance", "extraction", "approval"),
    sample={"invoice_text": INVOICE},
    graph=graph(
        [
            node(
                "start",
                "start",
                0,
                200,
                inputs=[field_("invoice_text", description="The invoice as plain text.")],
            ),
            node(
                "about",
                "note",
                0,
                0,
                text=(
                    "Extraction, the vendor check, the arithmetic check and the ERP record run "
                    "in parallel. Only invoices that add up, come from an approved vendor and stay "
                    "under its approval limit are posted without a reviewer."
                ),
                color="green",
            ),
            node(
                "extract",
                "llm",
                300,
                200,
                label="Extract invoice fields",
                settings={**RETRY, "cache_ttl_s": 3600},
                model="offline",
                temperature=0,
                max_tokens=1200,
                output_mode="json",
                system=(
                    "You extract structured data from supplier invoices for the finance team. "
                    "Copy values exactly as printed and write dates as YYYY-MM-DD."
                ),
                prompt="Extract the invoice fields.\n\nInvoice:\n{{inputs.invoice_text}}",
                json_fields=[
                    field_("vendor", description="Who issued the invoice."),
                    field_("invoice_number"),
                    field_("invoice_date"),
                    field_("due_date"),
                    field_("currency", description="ISO currency code."),
                    field_("subtotal", "number"),
                    field_("tax", "number"),
                    field_("total", "number", description="The amount due."),
                    field_("payment_terms"),
                    field_(
                        "line_items",
                        "array",
                        items="object",
                        fields=[
                            field_("description"),
                            field_("quantity", "number"),
                            field_("unit_price", "number"),
                            field_("amount", "number"),
                        ],
                    ),
                ],
            ),
            node(
                "vendor_lookup",
                "http",
                600,
                60,
                label="Check vendor in ERP",
                settings=RETRY,
                method="GET",
                url=f"{SANDBOX}/erp/vendors",
                query=[{"key": "name", "value": "{{extract.json.vendor}}"}],
                expect="json",
                fail_on_status=False,
            ),
            node(
                "check_totals",
                "calculator",
                600,
                200,
                label="Check the arithmetic",
                expression="round({{extract.json.subtotal}} + {{extract.json.tax}} - {{extract.json.total}}, 2)",
            ),
            node(
                "erp_record",
                "json_transform",
                600,
                340,
                label="Shape the ERP record",
                input="{{extract.json}}",
                expression=(
                    "{vendor: vendor, invoice_number: invoice_number, issued: invoice_date, "
                    "due: due_date, currency: currency, total: total, "
                    "lines: length(line_items || `[]`)}"
                ),
            ),
            node(
                "route",
                "condition",
                900,
                200,
                label="Post automatically?",
                routes=[
                    {
                        "id": "auto",
                        "label": "Auto-approve",
                        "match": "all",
                        "rules": [
                            {"left": "{{check_totals.result}}", "operator": "equals", "right": "0"},
                            {
                                "left": "{{vendor_lookup.json.status}}",
                                "operator": "equals",
                                "right": "approved",
                            },
                            {
                                "left": "{{extract.json.total}}",
                                "operator": "less_or_equal",
                                "right": "{{vendor_lookup.json.approval_limit}}",
                            },
                        ],
                    }
                ],
            ),
            node(
                "review",
                "approval",
                1200,
                300,
                label="Finance review",
                title="Approve invoice {{extract.json.invoice_number}} from {{extract.json.vendor}}",
                message=(
                    "Total: {{extract.json.currency}} {{extract.json.total}}\n"
                    "Vendor status: {{vendor_lookup.json.status | default('not found in ERP')}}\n"
                    "Approval limit: {{vendor_lookup.json.approval_limit | default('none')}}\n"
                    "Arithmetic difference: {{check_totals.result}}"
                ),
                expires_after_hours=72,
            ),
            node(
                "posted",
                "output",
                1200,
                100,
                label="Posted",
                fields=[
                    {"name": "status", "value": "posted"},
                    {"name": "record", "value": "{{erp_record.result}}"},
                ],
            ),
            node(
                "posted_after_review",
                "output",
                1500,
                220,
                label="Posted after review",
                fields=[
                    {"name": "status", "value": "posted after review"},
                    {"name": "record", "value": "{{erp_record.result}}"},
                    {"name": "reviewer_note", "value": "{{review.comment}}"},
                ],
            ),
            node(
                "rejected",
                "output",
                1500,
                380,
                label="Rejected",
                fields=[
                    {"name": "status", "value": "rejected"},
                    {"name": "reason", "value": "{{review.comment}}"},
                ],
            ),
        ],
        [
            edge("start", "extract"),
            edge("extract", "vendor_lookup"),
            edge("extract", "check_totals"),
            edge("extract", "erp_record"),
            edge("vendor_lookup", "route"),
            edge("check_totals", "route"),
            edge("erp_record", "route"),
            edge("route", "posted", "route_auto"),
            edge("route", "review", "else"),
            edge("review", "posted_after_review", "approved"),
            edge("review", "rejected", "rejected"),
        ],
    ),
)

# --------------------------------------------------------------------------------------
# Research brief from a knowledge base
# --------------------------------------------------------------------------------------

RESEARCH_BRIEF = Template(
    slug="research-brief",
    name="Research brief from a knowledge base",
    description=(
        "Breaks a topic into research questions, answers each one from the research library "
        "with citations (in parallel, in a loop) and writes a brief with a summary, key "
        "findings and recommendations."
    ),
    category="Research",
    tags=("research", "knowledge", "loop"),
    knowledge=(RESEARCH_LIBRARY,),
    sample={"topic": "Rolling out the new remote work policy", "audience": "People team leads"},
    graph=graph(
        [
            node(
                "start",
                "start",
                0,
                160,
                inputs=[
                    field_("topic", description="What the brief is about."),
                    field_(
                        "audience",
                        description="Who will read it.",
                        required=False,
                        default="the leadership team",
                    ),
                ],
            ),
            node(
                "about",
                "note",
                0,
                0,
                text=(
                    "The loop answers every question in parallel (three at a time). Each "
                    "answer cites its sources, and the brief keeps those citations."
                ),
                color="yellow",
            ),
            node(
                "plan",
                "llm",
                300,
                160,
                label="Plan research questions",
                settings=RETRY,
                model="offline",
                temperature=0,
                output_mode="json",
                system="You plan research. Break a topic into focused questions the documents can answer.",
                prompt=(
                    "Break this topic into three research questions.\n\n"
                    "Topic: {{inputs.topic}}\nAudience: {{inputs.audience}}"
                ),
                json_fields=[field_("questions", "array", items="string")],
            ),
            node(
                "each_question",
                "loop",
                600,
                160,
                label="For each question",
                items="{{plan.json.questions}}",
                max_items=5,
                concurrency=3,
                collect="### {{item}}\n{{answer.text}}",
            ),
            node(
                "search",
                "knowledge",
                600,
                340,
                label="Search the library",
                knowledge_base_id=kb(RESEARCH_LIBRARY),
                query="{{item}}",
                top_k=3,
            ),
            node(
                "answer",
                "llm",
                900,
                340,
                label="Answer with citations",
                settings=RETRY,
                model="offline",
                temperature=0,
                system=(
                    "Answer using only the sources. Cite them as [n]. If the sources do not "
                    "answer the question, say so."
                ),
                prompt="Answer the question.\n\nQuestion: {{item}}\n\nSources:\n{{search.context}}",
            ),
            node(
                "compose",
                "llm",
                1200,
                160,
                label="Write the brief",
                settings=RETRY,
                model="offline",
                temperature=0.2,
                max_tokens=1200,
                system="You write crisp research briefs for busy readers, in Markdown.",
                prompt=(
                    "Write a research brief.\n\nTopic: {{inputs.topic}}\nAudience: {{inputs.audience}}\n\n"
                    'Findings:\n{{each_question.results | join("\\n\\n")}}'
                ),
            ),
            node(
                "result",
                "output",
                1500,
                160,
                label="Brief",
                fields=[
                    {"name": "brief", "value": "{{compose.text}}"},
                    {"name": "questions", "value": "{{plan.json.questions}}"},
                    {"name": "questions_answered", "value": "{{each_question.count}}"},
                ],
            ),
        ],
        [
            edge("start", "plan"),
            edge("plan", "each_question"),
            edge("each_question", "search", "body"),
            edge("search", "answer"),
            edge("each_question", "compose", "done"),
            edge("compose", "result"),
        ],
    ),
)

# --------------------------------------------------------------------------------------
# Lead qualification
# --------------------------------------------------------------------------------------

LEAD_MESSAGE = (
    "Hi, we are evaluating tools to automate our support triage. We have about 120 agents and "
    "budget approved for this quarter. Could you send pricing and set up a demo next week?"
)

LEAD_QUALIFICATION = Template(
    slug="lead-qualification",
    name="Lead qualification",
    description=(
        "Enriches an inbound lead from the CRM, assesses intent and budget, and scores it. Hot "
        "leads get a personalized outreach email from an agent that searches the product docs "
        "and calculates a price; the rest get a friendly nurture email."
    ),
    category="Sales",
    tags=("sales", "agent", "tools"),
    knowledge=(PRODUCT_HANDBOOK,),
    sample={
        "name": "Priya Raman",
        "email": "priya.raman@initech.example",
        "company": "Initech",
        "message": LEAD_MESSAGE,
    },
    graph=graph(
        [
            node(
                "start",
                "start",
                0,
                220,
                inputs=[
                    field_("name"),
                    field_("email"),
                    field_("company"),
                    field_("message", description="What the lead wrote."),
                ],
            ),
            node(
                "about",
                "note",
                0,
                0,
                text=(
                    "Score = intent (0 to 50) + company size (up to 50). The outreach agent "
                    "decides for itself when to search the docs and when to calculate."
                ),
                color="pink",
            ),
            node(
                "enrich",
                "http",
                300,
                100,
                label="Enrich company",
                settings=RETRY,
                method="GET",
                url=f"{SANDBOX}/crm/companies/lookup",
                query=[{"key": "email", "value": "{{inputs.email}}"}],
                expect="json",
                fail_on_status=False,
            ),
            node(
                "assess",
                "llm",
                300,
                340,
                label="Assess intent",
                settings={**RETRY, "cache_ttl_s": 3600},
                model="offline",
                temperature=0,
                output_mode="json",
                system="You qualify inbound sales leads for Northwind Cloud.",
                prompt=(
                    "Read this inbound lead and assess it.\n\nName: {{inputs.name}}\n"
                    "Company: {{inputs.company}}\nEmail: {{inputs.email}}\n\n"
                    "Message:\n{{inputs.message}}"
                ),
                json_fields=[
                    field_(
                        "intent", enum=["purchase", "evaluation", "support", "partnership", "other"]
                    ),
                    field_("budget_mentioned", "boolean"),
                    field_("timeline", enum=["immediate", "this_quarter", "this_year", "unknown"]),
                    field_("seats", "integer", description="Seats or users they need."),
                    field_(
                        "intent_score", "integer", description="0 to 50: how ready they are to buy."
                    ),
                    field_("use_case", description="What they want to achieve."),
                ],
            ),
            node(
                "score",
                "calculator",
                600,
                220,
                label="Score the lead",
                expression=(
                    "min(100, {{assess.json.intent_score | default(0)}} + "
                    "min(50, {{enrich.json.employees | default(0)}} / 20))"
                ),
            ),
            node(
                "route",
                "condition",
                900,
                220,
                label="Hot lead?",
                routes=[
                    {
                        "id": "hot",
                        "label": "Hot",
                        "rules": [
                            {
                                "left": "{{score.result}}",
                                "operator": "greater_or_equal",
                                "right": "60",
                            }
                        ],
                    }
                ],
            ),
            node(
                "outreach",
                "agent",
                1200,
                100,
                label="Outreach agent",
                settings={"timeout_s": 180},
                model="offline",
                temperature=0.4,
                max_iterations=4,
                system=(
                    "You are a sales development rep at Northwind Cloud. Write warm, specific "
                    "emails under 150 words. Sign off as Jordan Lee, Northwind Cloud."
                ),
                task=(
                    "Write a personalized outreach email to {{inputs.name}} at {{inputs.company}} "
                    "({{enrich.json.employees}} employees, {{enrich.json.industry}}). They wrote: "
                    '"{{inputs.message}}" Search the product docs for pricing that fits '
                    "{{assess.json.seats | default(25)}} seats and calculate the annual price."
                ),
            ),
            node(
                "product_docs",
                "knowledge",
                1050,
                -60,
                label="Product docs",
                knowledge_base_id=kb(PRODUCT_HANDBOOK),
                top_k=3,
                tool_description="Search the product handbook for plans, pricing, features and security.",
            ),
            node(
                "pricing_calculator",
                "calculator",
                1350,
                -60,
                label="Pricing calculator",
                tool_name="calculator",
                tool_description="Arithmetic for prices and totals.",
            ),
            node(
                "nurture",
                "llm",
                1200,
                340,
                label="Nurture email",
                settings=RETRY,
                model="offline",
                temperature=0.4,
                system=(
                    "You write friendly nurture emails for Northwind Cloud. Keep it short and "
                    "helpful, with no pressure. Sign off as The Northwind team."
                ),
                prompt=(
                    "Draft a short nurture email to {{inputs.name}} at {{inputs.company}}. "
                    'They wrote: "{{inputs.message}}"'
                ),
            ),
            node(
                "hot_lead",
                "output",
                1500,
                100,
                label="Hot lead",
                fields=[
                    {"name": "tier", "value": "hot"},
                    {"name": "score", "value": "{{score.result}}"},
                    {"name": "intent", "value": "{{assess.json.intent}}"},
                    {"name": "email", "value": "{{outreach.text}}"},
                ],
            ),
            node(
                "nurture_lead",
                "output",
                1500,
                340,
                label="Nurture",
                fields=[
                    {"name": "tier", "value": "nurture"},
                    {"name": "score", "value": "{{score.result}}"},
                    {"name": "intent", "value": "{{assess.json.intent}}"},
                    {"name": "email", "value": "{{nurture.text}}"},
                ],
            ),
        ],
        [
            edge("start", "enrich"),
            edge("start", "assess"),
            edge("enrich", "score"),
            edge("assess", "score"),
            edge("score", "route"),
            edge("route", "outreach", "route_hot"),
            edge("route", "nurture", "else"),
            tool("product_docs", "outreach"),
            tool("pricing_calculator", "outreach"),
            edge("outreach", "hot_lead"),
            edge("nurture", "nurture_lead"),
        ],
    ),
)

# --------------------------------------------------------------------------------------
# Meeting notes to action items
# --------------------------------------------------------------------------------------

MEETING_NOTES = """Ava: Thanks everyone. The goal today is to agree the launch plan for the Atlas v2 beta.
Leo: Engineering is on track. The last blocker is the battery firmware, which should land on Thursday.
Maya: Support needs the release notes before we open the beta to customers.
Ava: Agreed. We decided to open the beta to 40 design partners on March 16.
Leo: I'll send the final firmware build to QA by Thursday.
Maya: I will draft the release notes and the support FAQ by next Monday.
Ava: Priya will schedule the kickoff call with the design partners.
Leo: One risk: if QA finds a regression, we may need to slip a week.
Ava: Let me update the board deck with the beta timeline by Friday."""

MEETING_ACTIONS = Template(
    slug="meeting-actions",
    name="Meeting notes to action items",
    description=(
        "Summarises meeting notes, extracts decisions and action items with owners and due "
        "dates, and creates one task per action item in the task tracker."
    ),
    category="Operations",
    tags=("meetings", "loop", "http"),
    sample={"title": "Atlas v2 beta launch sync", "notes": MEETING_NOTES},
    graph=graph(
        [
            node(
                "start",
                "start",
                0,
                160,
                inputs=[
                    field_("title", description="The meeting name."),
                    field_("notes", description="Notes or a transcript with speaker names."),
                ],
            ),
            node(
                "about",
                "note",
                0,
                0,
                text="The summary and the extraction run in parallel; tasks are created four at a time.",
                color="gray",
            ),
            node(
                "summarize",
                "llm",
                300,
                40,
                label="Summarize",
                settings=RETRY,
                model="offline",
                temperature=0.2,
                system="You write crisp meeting summaries.",
                prompt=(
                    "Summarize the meeting in three bullet points.\n\n"
                    "Meeting: {{inputs.title}}\n\nNotes:\n{{inputs.notes}}"
                ),
            ),
            node(
                "extract_actions",
                "llm",
                300,
                280,
                label="Extract action items",
                settings=RETRY,
                model="offline",
                temperature=0,
                output_mode="json",
                system="You extract commitments and decisions from meeting notes.",
                prompt=(
                    "Extract the action items and decisions.\n\n"
                    "Meeting: {{inputs.title}}\n\nNotes:\n{{inputs.notes}}"
                ),
                json_fields=[
                    field_(
                        "action_items",
                        "array",
                        items="object",
                        fields=[field_("owner"), field_("task"), field_("due")],
                    ),
                    field_("decisions", "array", items="string"),
                ],
            ),
            node(
                "each_action",
                "loop",
                600,
                280,
                label="For each action item",
                items="{{extract_actions.json.action_items}}",
                max_items=50,
                concurrency=4,
                collect="{{create_task.json.id}}",
            ),
            node(
                "create_task",
                "http",
                900,
                400,
                label="Create task",
                settings=RETRY,
                method="POST",
                url=f"{SANDBOX}/tasks",
                body_mode="json",
                body=(
                    '{"title": {{item.task | json}}, "assignee": {{item.owner | json}}, '
                    '"due": {{item.due | json}}, "source": {{inputs.title | json}}}'
                ),
                expect="json",
            ),
            node(
                "result",
                "output",
                1200,
                160,
                label="Summary and tasks",
                fields=[
                    {"name": "summary", "value": "{{summarize.text}}"},
                    {"name": "decisions", "value": "{{extract_actions.json.decisions}}"},
                    {"name": "tasks", "value": "{{each_action.results}}"},
                    {"name": "task_count", "value": "{{each_action.count}}"},
                ],
            ),
        ],
        [
            edge("start", "summarize"),
            edge("start", "extract_actions"),
            edge("extract_actions", "each_action"),
            edge("each_action", "create_task", "body"),
            edge("summarize", "result"),
            edge("each_action", "result", "done"),
        ],
    ),
)

# --------------------------------------------------------------------------------------
# HR policy assistant
# --------------------------------------------------------------------------------------

POLICY_ASSISTANT = Template(
    slug="policy-assistant",
    name="HR policy assistant",
    description=(
        "An agent that answers employee questions from the employee handbook, quoting the "
        "policy and citing the section, with a calculator for questions about amounts."
    ),
    category="People",
    tags=("agent", "knowledge", "hr"),
    knowledge=(EMPLOYEE_HANDBOOK,),
    sample={"question": "How many vacation days do full-time employees get each year?"},
    graph=graph(
        [
            node(
                "start",
                "start",
                0,
                160,
                inputs=[field_("question", description="The employee's question.")],
            ),
            node(
                "answer",
                "agent",
                300,
                160,
                label="Policy agent",
                settings={"timeout_s": 120},
                model="offline",
                temperature=0,
                max_iterations=3,
                system=(
                    "You answer employee questions using the employee handbook. Quote the policy "
                    "precisely, cite the section in brackets, and say when the handbook does not "
                    "cover something."
                ),
                task="Answer the employee's question using the handbook.\n\nQuestion: {{inputs.question}}",
            ),
            node(
                "search_policies",
                "knowledge",
                150,
                0,
                label="Employee handbook",
                knowledge_base_id=kb(EMPLOYEE_HANDBOOK),
                top_k=3,
                tool_description="Search the employee handbook.",
            ),
            node(
                "calculator",
                "calculator",
                450,
                0,
                label="Calculator",
                tool_description="Arithmetic for days, amounts and allowances.",
            ),
            node(
                "result",
                "output",
                600,
                160,
                label="Answer",
                fields=[
                    {"name": "answer", "value": "{{answer.text}}"},
                    {"name": "tools_used", "value": "{{answer.tool_calls | length}}"},
                ],
            ),
        ],
        [
            edge("start", "answer"),
            edge("answer", "result"),
            tool("search_policies", "answer"),
            tool("calculator", "answer"),
        ],
    ),
)


def _with_sample(template: Template) -> Template:
    """Store the sample inputs in the Start node too: the run dialog and exports use them."""
    graph_copy = copy.deepcopy(template.graph)
    for item in graph_copy["nodes"]:
        if item["type"] == "start":
            item["config"]["sample"] = dict(template.sample)
    return replace(template, graph=graph_copy)


TEMPLATES: tuple[Template, ...] = tuple(
    _with_sample(template)
    for template in (
        SUPPORT_TRIAGE,
        INVOICE_EXTRACTION,
        RESEARCH_BRIEF,
        LEAD_QUALIFICATION,
        MEETING_ACTIONS,
        POLICY_ASSISTANT,
    )
)
