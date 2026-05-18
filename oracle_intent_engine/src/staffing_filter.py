"""
Filters IT staffing firms and Oracle/JDE SI partners from company signals.

Key philosophy:
  - If a signal comes FROM an SI firm (IBM, PwC, Wipro, etc.), we don't
    simply drop it — we first try to extract the END CLIENT from the
    description. If a client is found, the signal is CONVERTED to use
    the client company instead. Only dropped if no client can be extracted.
  - Pure body-shopping / staffing firms with no client info are always dropped.

Three-level approach:
  1. Try end-client extraction for known SI partners
  2. Exact normalised-name blocklist (fastest, catches major firms)
  3. Keyword heuristic on company name (catches long-tail staffing firms)
"""

import re
from src.utils import get_logger, clean_text, is_valid_company_name

logger = get_logger(__name__)

# ── Major SI partners — we try client extraction BEFORE dropping ─────────────
# These firms post job ads and case studies on behalf of end clients.
_SI_PARTNERS: set[str] = {
    # ── Big 4 & global management consulting ─────────────────────────────────
    "accenture", "accenture federal services", "accenture consulting",
    "deloitte", "deloitte consulting", "deloitte digital", "deloitte touche",
    "kpmg", "kpmg consulting", "kpmg advisory",
    "pwc", "pricewaterhousecoopers", "pwc consulting",
    "ernst young", "ey", "ey consulting", "ernst & young",
    "grant thornton", "grant thornton llp",
    "bdo", "bdo digital", "bdo consulting",
    "rsm", "rsm us", "rsm consulting",
    "crowe", "crowe llp",
    "moss adams", "plante moran",
    "mckinsey", "mckinsey & company",
    "bcg", "boston consulting group",
    "bain", "bain & company",
    "oliver wyman", "roland berger",
    "a.t. kearney", "kearney",
    # ── Global IT services / offshore SIs ────────────────────────────────────
    "ibm", "ibm consulting", "ibm global business services", "ibm gbs",
    "ibm global services", "ibm issc",
    "infosys", "infosys bpm", "infosys consulting",
    "wipro", "wipro limited", "wipro technologies",
    "tcs", "tata consultancy services", "tata consulting",
    "hcl", "hcl technologies", "hcltech", "hcl infosystems",
    "tech mahindra", "tech mahindra limited",
    "mphasis", "mphasis limited",
    "cognizant", "cognizant technology solutions",
    "capgemini", "capgemini consulting", "capgemini sogeti",
    "birlasoft", "birlasoft limited",
    "hexaware", "hexaware technologies",
    "zensar", "zensar technologies",
    "ntt data", "ntt data services", "ntt",
    "dxc technology", "dxc", "dxc consulting",
    "unisys", "unisys corporation",
    "atos", "atos consulting", "atos origin",
    "sopra steria", "sopra consulting",
    "fujitsu", "fujitsu consulting",
    "logicalis", "logicalis group",
    "stefanini", "stefanini group",
    "igate", "igate corporation",
    "ciber", "ciber consulting",
    "epam systems", "epam",
    "globant",
    "slalom", "slalom consulting",
    "thoughtworks",
    "publicis sapient", "sapient", "sapient consulting", "sapient corporation",
    "avanade",
    "rizing",
    "saic", "science applications international",
    "leidos", "mantech",
    "booz allen hamilton", "booz allen",
    "cgi", "cgi group", "cgi federal",
    "dimension data", "ntt dimension data",
    "sirius computer solutions", "sirius",
    "presidio",
    "softchoice",
    "cdw", "cdw corporation",
    "insight direct", "insight enterprises",
    "computacenter",
    "wesco international", "wesco",
    "bertelsmann", "arvato",
    "mindtree",
    "lti", "larsen toubro infotech", "ltimindtree",
    "persistent systems",
    "niit technologies", "niit",
    # ── JDE-specific SIs (direct InoApps competitors) ────────────────────────
    "syntax", "syntax systems",
    "denovo", "denovo consulting",
    "terillium",
    "steltix",
    "resolution it",
    "collaborate business solutions", "cbs",
    "velocity technology solutions",
    "jade global",
    "everge group", "everge",
    "astute business solutions",
    "baker tilly digital", "baker tilly",
    "hitachi solutions", "hitachi consulting",
    "spinnaker support",
    "rimini street",
    "lortek",
    "xtend it",
    "mastek", "mastech",
    "namos", "namos solutions",
    "evosys", "keste", "certus", "mythics",
    "circular edge",
    "edgewater consulting",
    "clarkston consulting",
    "sierra-cedar", "sierra cedar",
    "collaborative solutions",
    "inoapps",   # shouldn't surface ourselves
    "linium",
    "xellera informatics", "xellera",
    "unilogix", "unilogix solutions",
    "redrock consulting",
    "bluefin solutions", "bluefin",
    "cedar consulting",
    "benchmark solutions",
    "ifs consultants", "ifs world",
    # ── Oracle-specific consulting brands ────────────────────────────────────
    "oracle consulting", "oracle cloud consulting",
    "sierra systems",   # acquired by ntt data
    "deloitte federal",
    "accenture technology solutions",
    "rounding group",
}

# ── Pure staffing / body-shopping — always drop, no client extraction ────────
_PURE_STAFFING: set[str] = {
    # US staffing
    "robert half", "robert half technology", "robert half international",
    "kforce", "teksystems", "tek systems", "insight global",
    "cybercoders", "modis", "staffmark", "staffmark group",
    "volt information sciences", "volt",
    "randstad", "randstad technologies", "randstad sourceright",
    "adecco", "adecco group",
    "manpower", "manpowergroup", "manpower group",
    "experis",  # manpower's it brand
    "kelly services", "kelly", "kellyocg",
    "spherion",
    "apex group", "apex systems",
    "allegis group", "allegis",
    "aerotek",  # allegis brand
    "teksystems",  # allegis brand
    "pontoon solutions", "pontoon",
    "recruitment solutions",
    "global consultants",
    # UK / European staffing
    "harvey nash", "harvey nash group",
    "hays", "hays recruitment", "hays technology", "hays plc",
    "pagegroup", "michael page", "page executive",
    "spring group", "spring technology",
    "computer futures",
    "penna",
    "sos recruitment",
    "blue arrow", "blue arrow staffing",
    "gi group",
    "cpl resources", "cpl group",
    "morgan hunt",
    "nrl group",
    "la international",
    # India staffing
    "teamlease", "teamlease services",
    "quess corp", "quess",
    "firstsource",
    "rchilli",
    # Oracle itself is not a prospect
    "oracle america", "oracle corporation", "oracle",
    "oracle uk", "oracle emea",
}

# ── Keyword patterns that indicate staffing / body-shopping ─────────────────
_STAFFING_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(staffing|recruiting|recruitment|resourcing)\b", re.I),
    re.compile(r"\b(staff augment|body shop|body-shop|outstaffing)\b", re.I),
    re.compile(r"\b(talent acquisition|talent solutions|workforce solutions)\b", re.I),
    re.compile(r"\b(contract staffing|contingent workforce|temp agency)\b", re.I),
]

# ── Keyword patterns that flag an SI / consulting firm (not staffing) ────────
_SI_KEYWORD_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(erp consulting|erp implementation|erp partner|oracle partner)\b", re.I),
    re.compile(r"\b(jde partner|jd edwards partner|jde consulting|jde implementation)\b", re.I),
    re.compile(r"\b(systems integrator|systems integration|si partner)\b", re.I),
    re.compile(r"\b(implementation partner|delivery partner|solution partner)\b", re.I),
    re.compile(r"\bmanaged services\b", re.I),
]

# Job title patterns indicating a contractor role FOR a client
_CONTRACTOR_TITLE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(contract(or)?|freelance|c2c|corp.?to.?corp)\b", re.I),
    re.compile(r"\b(resource manager|bench resource|resource pool)\b", re.I),
]

# ── Patterns to extract END CLIENT from SI job postings / descriptions ───────
_END_CLIENT_PATTERNS: list[re.Pattern] = [
    # "for our client, Barratt Developments"
    re.compile(
        r"for\s+(?:our\s+(?:key\s+)?client|a\s+(?:key\s+)?client)[,:\s]+([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)(?=\s+(?:in|based|located|who|is|a\s)|\.|,|$)",
        re.I,
    ),
    # "end client: National Grid"
    re.compile(
        r"end[\s\-]?client[:\s]+([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)(?=\s+(?:in|based|is)|\.|,|$)",
        re.I,
    ),
    # "client: BP plc" or "client name: BP"
    re.compile(
        r"\bclient(?:\s+name)?[:\s]+([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)(?=\s+(?:in|based|is)|\.|,|$)",
        re.I,
    ),
    # "deployed at / working at / on-site at Rolls Royce"
    re.compile(
        r"(?:deployed\s+at|working\s+at|on[\s\-]?site\s+at|based\s+at)\s+([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)(?=\s+(?:in|based|is)|\.|,|$)",
        re.I,
    ),
    # "on behalf of Barratt"
    re.compile(
        r"on\s+behalf\s+of\s+([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)(?=\s+(?:in|based|to|for)|\.|,|$)",
        re.I,
    ),
    # "helps [Client] implement JD Edwards" — SI success story pattern
    re.compile(
        r"(?:helps?|assisted?|enabled?|implemented?\s+for|deployed?\s+for)\s+([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)(?=\s+(?:to|with|achieve|improve|transform|implement|deploy|migrate))",
        re.I,
    ),
    # "[Client] selects / goes live / migrates"
    re.compile(
        r"^([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:selects?|goes?\s+live|went\s+live|migrates?|implements?|upgrades?|deploys?)",
        re.I,
    ),
    # "customer: [Client]" or "organisation: [Client]"
    re.compile(
        r"(?:customer|organisation|organization)[:\s]+([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)(?=[\.\,]|$)",
        re.I,
    ),
]

# Words that indicate we extracted the SI name, not the client
_SI_WORDS: set[str] = {
    "accenture", "deloitte", "pwc", "kpmg", "ey", "ibm", "infosys",
    "wipro", "hcl", "tcs", "capgemini", "cgi", "ntt", "dxc", "unisys",
    "syntax", "denovo", "terillium", "steltix", "mastek", "mastech",
    "namos", "evosys", "keste", "certus", "mythics", "birlasoft",
    "hexaware", "zensar", "mphasis", "cognizant", "mindtree",
    "spinnaker", "rimini", "oracle", "microsoft", "sap",
    # Extended
    "atos", "sopra", "fujitsu", "logicalis", "stefanini", "epam",
    "globant", "slalom", "thoughtworks", "sapient", "publicis",
    "avanade", "rizing", "saic", "leidos", "booz", "sirius",
    "presidio", "hitachi", "baker", "grant", "rsm", "bdo", "crowe",
    "circular", "edgewater", "clarkston", "sierra", "collaborative",
    "linium", "xellera", "unilogix", "redrock", "bluefin", "cedar",
    "benchmark", "lti", "larsen", "persistent", "niit",
    "tech mahindra", "dimension", "computacenter", "cdw", "insight",
}


def _normalise(name: str) -> str:
    name = clean_text(name)
    suffixes = [
        " inc", " inc.", " corp", " corp.", " ltd", " ltd.", " llc",
        " l.l.c", " group", " co.", " co", " gmbh", " s.a.", " plc",
        " ag", " nv", " bv", " lp", " llp",
    ]
    low = name.lower()
    for s in suffixes:
        if low.endswith(s):
            name = name[: -len(s)]
            low = name.lower()
    return low.strip()


def _is_si_partner(company_name: str) -> bool:
    if _normalise(company_name) in _SI_PARTNERS:
        return True
    for pat in _SI_KEYWORD_PATTERNS:
        if pat.search(company_name):
            return True
    return False


def _is_pure_staffing(company_name: str) -> bool:
    norm = _normalise(company_name)
    if norm in _PURE_STAFFING:
        return True
    for pat in _STAFFING_PATTERNS:
        if pat.search(company_name):
            return True
    return False


def _is_contractor_signal(signal: dict) -> bool:
    title = signal.get("job_title", "")
    for pat in _CONTRACTOR_TITLE_PATTERNS:
        if pat.search(title):
            return True
    return False


def _extract_end_client(signal: dict) -> str:
    """
    Try to find the end client company in a signal that came from an SI firm.
    Checks job_title + description. Returns client name or empty string.
    """
    text = f"{signal.get('job_title', '')} {signal.get('description', '')}"
    for pat in _END_CLIENT_PATTERNS:
        m = pat.search(text)
        if m:
            candidate = m.group(1).strip().rstrip(".,;:")
            # Reject if we just matched the SI firm itself
            if candidate.lower().split()[0] in _SI_WORDS:
                continue
            if is_valid_company_name(candidate) and len(candidate) > 3:
                return candidate
    return ""


def filter_signals(signals: list[dict]) -> tuple[list[dict], int]:
    """
    Process signals from SI partners and staffing firms:
      - SI partner signal WITH extractable end client → convert + keep
      - SI partner signal WITHOUT end client → drop
      - Pure staffing firm → always drop
      - Contractor title signal → attempt client extraction, else drop
    Returns (filtered_signals, removed_count).
    """
    kept, removed = [], 0

    for sig in signals:
        company = sig.get("company_name", "")

        # Pure staffing — no client extraction, always drop
        if _is_pure_staffing(company):
            logger.debug(f"Filtered (pure staffing): {company}")
            removed += 1
            continue

        # Known SI partner — try to extract end client
        if _is_si_partner(company):
            client = _extract_end_client(sig)
            if client:
                logger.debug(f"SI client extracted: {client} (via {company})")
                sig = dict(sig)  # don't mutate original
                sig["company_name"] = client
                sig["si_partner"] = company  # preserve who sourced it
                kept.append(sig)
            else:
                logger.debug(f"Filtered (SI, no client found): {company}")
                removed += 1
            continue

        # Contractor title — try client extraction, else drop
        if _is_contractor_signal(sig):
            client = _extract_end_client(sig)
            if client:
                logger.debug(f"Contractor client extracted: {client}")
                sig = dict(sig)
                sig["company_name"] = client
                kept.append(sig)
            else:
                logger.debug(f"Filtered (contractor title): {sig.get('job_title')} @ {company}")
                removed += 1
            continue

        kept.append(sig)

    return kept, removed


def is_staffing_firm(company_name: str) -> bool:
    """Public helper — used by aggregator to drop whole-company buckets."""
    return _is_pure_staffing(company_name) or _is_si_partner(company_name)
