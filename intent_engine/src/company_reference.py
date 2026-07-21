"""
company_reference.py
====================
Curated domain → canonical company identity for the highest-volume accounts in
the validated corpus. The raw Salesforce export mangles names ("Bofa",
"Jpmorgan", "Wellsfargo"); this maps each domain to a proper name, industry,
and HQ location (verified against public sources).

Two payoffs:
  * proper display names + industry + location for the Pipeline UI
  * consolidation — several domains map to one parent (jpmorgan.com /
    jpmchase.com / chase.com → JPMorgan Chase), collapsing duplicate company
    rows so the count reflects real companies, not name spellings.

Domains not listed here fall back to algorithmic name cleanup + a location
derived from their contacts' mailing addresses (see import_contacts.py).
"""

from __future__ import annotations

# domain: (proper_name, industry, city, state, country)
COMPANY_REFERENCE: dict[str, tuple[str, str, str, str, str]] = {
    "oracle.com":        ("Oracle", "Technology", "Austin", "TX", "USA"),
    "bofa.com":          ("Bank of America", "Banking", "Charlotte", "NC", "USA"),
    "siemens.com":       ("Siemens", "Industrial Manufacturing", "Munich", "", "Germany"),
    "jpmorgan.com":      ("JPMorgan Chase", "Banking", "New York", "NY", "USA"),
    "jpmchase.com":      ("JPMorgan Chase", "Banking", "New York", "NY", "USA"),
    "chase.com":         ("JPMorgan Chase", "Banking", "New York", "NY", "USA"),
    "citi.com":          ("Citigroup", "Banking", "New York", "NY", "USA"),
    "citigroup.com":     ("Citigroup", "Banking", "New York", "NY", "USA"),
    "unilever.com":      ("Unilever", "Consumer Goods", "London", "", "UK"),
    "emerson.com":       ("Emerson Electric", "Industrial Manufacturing", "St. Louis", "MO", "USA"),
    "siemens-energy.com":("Siemens Energy", "Energy", "Munich", "", "Germany"),
    "marriott.com":      ("Marriott International", "Hospitality", "Bethesda", "MD", "USA"),
    "barclays.com":      ("Barclays", "Banking", "London", "", "UK"),
    "bosch.com":         ("Robert Bosch", "Industrial Manufacturing", "Gerlingen", "", "Germany"),
    "wellsfargo.com":    ("Wells Fargo", "Banking", "San Francisco", "CA", "USA"),
    "rolls-royce.com":   ("Rolls-Royce Holdings", "Aerospace & Defense", "London", "", "UK"),
    "ihg.com":           ("InterContinental Hotels Group", "Hospitality", "Windsor", "", "UK"),
    "pnc.com":           ("PNC Financial Services", "Banking", "Pittsburgh", "PA", "USA"),
    "honeywell.com":     ("Honeywell", "Industrial Manufacturing", "Charlotte", "NC", "USA"),
    "amazon.com":        ("Amazon", "Technology", "Seattle", "WA", "USA"),
    "pepsico.com":       ("PepsiCo", "Consumer Goods", "Purchase", "NY", "USA"),
    "statestreet.com":   ("State Street", "Financial Services", "Boston", "MA", "USA"),
    "baesystems.com":    ("BAE Systems", "Aerospace & Defense", "Farnborough", "", "UK"),
    "fidelity.com":      ("Fidelity Investments", "Financial Services", "Boston", "MA", "USA"),
    "fmr.com":           ("Fidelity Investments", "Financial Services", "Boston", "MA", "USA"),
    "dell.com":          ("Dell Technologies", "Technology", "Round Rock", "TX", "USA"),
    "ford.com":          ("Ford Motor Company", "Automotive", "Dearborn", "MI", "USA"),
    "basf.com":          ("BASF", "Chemicals", "Ludwigshafen", "", "Germany"),
    "fedex.com":         ("FedEx", "Logistics", "Memphis", "TN", "USA"),
    "astrazeneca.com":   ("AstraZeneca", "Pharmaceuticals", "Cambridge", "", "UK"),
    "usaa.com":          ("USAA", "Insurance", "San Antonio", "TX", "USA"),
    "metlife.com":       ("MetLife", "Insurance", "New York", "NY", "USA"),
    "eaton.com":         ("Eaton", "Industrial Manufacturing", "Dublin", "", "Ireland"),
    "citizensbank.com":  ("Citizens Financial Group", "Banking", "Providence", "RI", "USA"),
    "aig.com":           ("AIG", "Insurance", "New York", "NY", "USA"),
    "gartner.com":       ("Gartner", "Research & Advisory", "Stamford", "CT", "USA"),
    "truist.com":        ("Truist Financial", "Banking", "Charlotte", "NC", "USA"),
    "thyssenkrupp.com":  ("thyssenkrupp", "Industrial Manufacturing", "Essen", "", "Germany"),
    "prudential.com":    ("Prudential Financial", "Insurance", "Newark", "NJ", "USA"),
    "disney.com":        ("The Walt Disney Company", "Media & Entertainment", "Burbank", "CA", "USA"),
}


def lookup(domain: str):
    """Return (name, industry, city, state, country) or None."""
    return COMPANY_REFERENCE.get((domain or "").strip().lower())
