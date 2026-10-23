"""Fixture data for the sandbox API. Every company, person and domain here is fictional."""

from __future__ import annotations

from typing import Any

CONTACTS: dict[str, dict[str, Any]] = {
    "dana.whitfield@globex.example": {
        "name": "Dana Whitfield",
        "company": "Globex Corporation",
        "plan": "enterprise",
        "mrr_usd": 4200,
        "account_manager": "Sam Rivera",
        "customer_since": "2023-04-12",
    },
    "marco.rossi@initech.example": {
        "name": "Marco Rossi",
        "company": "Initech",
        "plan": "business",
        "mrr_usd": 1150,
        "account_manager": "Sam Rivera",
        "customer_since": "2024-09-02",
    },
    "li.wei@umbrella.example": {
        "name": "Li Wei",
        "company": "Umbrella Health",
        "plan": "starter",
        "mrr_usd": 290,
        "account_manager": None,
        "customer_since": "2025-11-20",
    },
    "olivia.brown@hooli.example": {
        "name": "Olivia Brown",
        "company": "Hooli",
        "plan": "enterprise",
        "mrr_usd": 9800,
        "account_manager": "Priya Shah",
        "customer_since": "2022-06-30",
    },
    "tom.becker@brightside.example": {
        "name": "Tom Becker",
        "company": "Brightside Bakery",
        "plan": "starter",
        "mrr_usd": 49,
        "account_manager": None,
        "customer_since": "2026-02-14",
    },
    "ana.silva@starklogistics.example": {
        "name": "Ana Silva",
        "company": "Stark Logistics",
        "plan": "business",
        "mrr_usd": 2350,
        "account_manager": "Priya Shah",
        "customer_since": "2024-01-08",
    },
    "james.okafor@waynefoods.example": {
        "name": "James Okafor",
        "company": "Wayne Foods",
        "plan": "business",
        "mrr_usd": 1780,
        "account_manager": "Sam Rivera",
        "customer_since": "2025-03-17",
    },
}

COMPANIES: dict[str, dict[str, Any]] = {
    "initech.example": {
        "name": "Initech",
        "industry": "Financial services",
        "employees": 480,
        "annual_revenue_usd": 92_000_000,
        "region": "North America",
        "existing_customer": True,
        "tech_stack": ["Zendesk", "Salesforce", "Snowflake"],
    },
    "globex.example": {
        "name": "Globex Corporation",
        "industry": "Manufacturing",
        "employees": 3200,
        "annual_revenue_usd": 610_000_000,
        "region": "Europe",
        "existing_customer": True,
        "tech_stack": ["ServiceNow", "SAP"],
    },
    "hooli.example": {
        "name": "Hooli",
        "industry": "Technology",
        "employees": 12000,
        "annual_revenue_usd": 4_100_000_000,
        "region": "North America",
        "existing_customer": True,
        "tech_stack": ["Jira", "Okta", "BigQuery"],
    },
    "brightside.example": {
        "name": "Brightside Bakery",
        "industry": "Food and beverage",
        "employees": 18,
        "annual_revenue_usd": 2_400_000,
        "region": "Europe",
        "existing_customer": False,
        "tech_stack": ["Shopify"],
    },
    "piedpiper.example": {
        "name": "Pied Piper",
        "industry": "Software",
        "employees": 85,
        "annual_revenue_usd": 14_000_000,
        "region": "North America",
        "existing_customer": False,
        "tech_stack": ["HubSpot", "Intercom"],
    },
    "soylent.example": {
        "name": "Soylent Foods",
        "industry": "Consumer goods",
        "employees": 760,
        "annual_revenue_usd": 180_000_000,
        "region": "Asia Pacific",
        "existing_customer": False,
        "tech_stack": ["Freshdesk", "Microsoft Dynamics"],
    },
    "massivedynamic.example": {
        "name": "Massive Dynamic",
        "industry": "Research",
        "employees": 2100,
        "annual_revenue_usd": 520_000_000,
        "region": "North America",
        "existing_customer": False,
        "tech_stack": ["Salesforce", "Zendesk"],
    },
}

PERSONAL_DOMAINS = frozenset(
    {"gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com", "proton.me", "aol.com"}
)

INDUSTRIES = (
    "Software",
    "Retail",
    "Healthcare",
    "Logistics",
    "Education",
    "Financial services",
    "Media",
    "Hospitality",
)
REGIONS = ("North America", "Europe", "Asia Pacific", "Latin America")

VENDORS: dict[str, dict[str, Any]] = {
    "acme office supplies": {
        "vendor_id": "V-1001",
        "name": "Acme Office Supplies Ltd",
        "status": "approved",
        "payment_terms": "Net 30",
        "approval_limit": 5000,
        "currency": "GBP",
    },
    "contoso cloud services": {
        "vendor_id": "V-1002",
        "name": "Contoso Cloud Services",
        "status": "approved",
        "payment_terms": "Net 45",
        "approval_limit": 25000,
        "currency": "USD",
    },
    "fabrikam logistics": {
        "vendor_id": "V-1003",
        "name": "Fabrikam Logistics",
        "status": "on_hold",
        "hold_reason": "Bank details under review",
        "payment_terms": "Net 30",
        "approval_limit": 10000,
        "currency": "EUR",
    },
    "northwind catering": {
        "vendor_id": "V-1004",
        "name": "Northwind Catering Co",
        "status": "approved",
        "payment_terms": "Net 15",
        "approval_limit": 1500,
        "currency": "EUR",
    },
    "tailspin software": {
        "vendor_id": "V-1005",
        "name": "Tailspin Software",
        "status": "approved",
        "payment_terms": "Net 30",
        "approval_limit": 12000,
        "currency": "USD",
    },
}

FX_RATES: dict[str, dict[str, float]] = {
    "USD": {"EUR": 0.92, "GBP": 0.79, "INR": 83.2, "JPY": 151.4, "AUD": 1.52},
    "EUR": {"USD": 1.087, "GBP": 0.859, "INR": 90.4, "JPY": 164.6, "AUD": 1.65},
    "GBP": {"USD": 1.266, "EUR": 1.164, "INR": 105.3, "JPY": 191.6, "AUD": 1.92},
}
FX_AS_OF = "2026-10-01"
