"""
Industry name normalization.

Maps raw Apollo / scraped industry strings → clean canonical English names.
Used both when saving companies and when building the filter dropdown.
"""

import re

# canonical name → list of raw variants that map to it
_CANONICAL: dict[str, list[str]] = {
    "Manufacturing": [
        "manufacturing", "industrial manufacturing",
    ],
    "Pharmaceuticals": [
        "pharmaceuticals", "pharmaceutical manufacturing", "pharma",
        "pharmaceutical", "drug manufacturing",
    ],
    "Food & Beverages": [
        "food production", "food & beverages", "food & beverage",
        "food & beverage manufacturing", "food and beverage manufacturing",
        "food and beverages", "food processing",
    ],
    "Oil & Gas": [
        "oil & energy", "oil & gas", "oil, gas and mining",
        "oil, gas and mining", "oil and gas",
    ],
    "Energy & Utilities": [
        "energy", "energy, utilities & waste", "utilities",
        "electric utilities", "oil and energy",
    ],
    "Information Technology": [
        "information technology & services", "information technology",
        "it services & consulting", "technology", "tech",
        "computer software", "software", "internet",
        "media & internet", "computer & network security",
    ],
    "Financial Services": [
        "financial services", "banking", "finance",
        "investment management", "capital markets",
        "venture capital & private equity",
    ],
    "Insurance": [
        "insurance",
    ],
    "Real Estate": [
        "real estate", "homebuilding", "homebuilders",
        "commercial real estate",
    ],
    "Construction": [
        "construction", "civil engineering", "homebuilding",
    ],
    "Building Materials": [
        "building materials", "wholesale - building materials",
        "aggregates / construction materials", "aggregates / ready-mix concrete",
    ],
    "Transportation & Logistics": [
        "transportation", "transportation/trucking/railroad",
        "transportation & logistics", "logistics & supply chain",
        "trucking", "maritime", "airlines/aviation",
        "transport, logistiek, supplychain en opslag",  # Dutch
    ],
    "Healthcare": [
        "healthcare", "hospital & health care", "hospitals & physicians clinics",
        "health, wellness & fitness", "medical practice",
    ],
    "Medical Devices": [
        "medical devices", "medical device manufacturing",
    ],
    "Automotive": [
        "automotive", "automotive manufacturing",
    ],
    "Chemicals": [
        "chemicals", "chemical manufacturing", "plastics",
    ],
    "Mining & Metals": [
        "mining", "mining & metals", "minerals & mining",
        "oil, gas and mining",
    ],
    "Machinery & Engineering": [
        "machinery", "machinery manufacturing",
        "mechanical or industrial engineering",
        "industrial machinery mfg",
    ],
    "Aerospace & Defense": [
        "aerospace & defense", "aerospace parts mfg",
        "defense & space",
    ],
    "Consumer Electronics": [
        "consumer electronics mfg", "consumer electronics",
        "semiconductors", "electrical/electronic manufacturing",
    ],
    "Consumer Goods": [
        "consumer goods", "consumer services",
        "retail", "retail - apparel",
        "apparel & fashion", "sporting goods",
    ],
    "Staffing & Recruiting": [
        "staffing & recruiting", "human resources",
    ],
    "Business Services": [
        "business services", "management consulting",
        "facilities services", "outsourcing/offshoring",
    ],
    "Marketing & Advertising": [
        "marketing & advertising", "public relations & communications",
    ],
    "Agriculture": [
        "agriculture", "farming", "paper & forest products",
    ],
    "Wholesale & Distribution": [
        "wholesale", "wholesale distribution", "distribution",
    ],
    "Government": [
        "government", "government administration",
        "military", "law enforcement",
    ],
    "Education": [
        "education", "higher education", "e-learning",
        "primary/secondary education",
    ],
    "Hospitality & Restaurants": [
        "hospitality", "restaurants",
        "services de restauration",  # French
    ],
    "Nonprofit & Organizations": [
        "nonprofit organization management", "organizations",
        "civic & social organization",
    ],
    "Telecommunications": [
        "telecommunications", "wireless",
    ],
    "Research & Development": [
        "research", "biotechnology",
    ],
    "Media & Publishing": [
        "publishing", "media production", "broadcast media",
        "entertainment",
    ],
    "Environmental Services": [
        "environmental services", "renewables & environment",
    ],
    "Packaging": [
        "packaging & containers",
    ],
    "Holding Companies": [
        "holding companies & conglomerates", "conglomerate",
    ],
}

# Build reverse lookup: raw_lower → canonical
_REVERSE: dict[str, str] = {}
for canonical, variants in _CANONICAL.items():
    for v in variants:
        _REVERSE[v.lower().strip()] = canonical


def normalize(raw: str) -> str:
    """
    Return a clean canonical industry name for a raw Apollo string.
    Falls back to Title Case of the original if no mapping found.
    Returns '' for blank/None input.
    """
    if not raw:
        return ""
    cleaned = raw.strip().lower()
    # Direct lookup
    if cleaned in _REVERSE:
        return _REVERSE[cleaned]
    # Partial match — check if any key is contained in the raw string
    for key, canonical in _REVERSE.items():
        if key in cleaned:
            return canonical
    # Fall back: title-case the original, collapse slash-variants
    cleaned = re.sub(r"\s*/\s*", " / ", raw.strip())
    return cleaned.title()
