"""
Partner Case Study signal — Oracle & JDE SI partners and boutique consultancies.

Uses Bing RSS (free, no key) to find case studies, success stories, and
job postings from Oracle/JDE implementation partners.
Extracts the END CLIENT company from each result — not the SI partner itself.

Covers:
  - Big 4 / global SIs (IBM, PwC, Deloitte, Accenture, Capgemini, etc.)
  - Oracle Cloud SIs (Infosys, Wipro, HCL, Mastek, Evosys, etc.)
  - JDE specialist SIs (Syntax, Denovo, Terillium,
    Steltix, Wipro/Edgewater, HCL/Ciber, Spinnaker, Rimini Street, etc.)
"""

import re
import urllib.parse
import feedparser
from src.signals.base_signal import BaseSignal
from src.utils import get_logger, clean_text, truncate, is_valid_company_name, random_delay

logger = get_logger(__name__)

BING_RSS = "https://www.bing.com/news/search?format=rss&q="

# ── Oracle Cloud SI partners ─────────────────────────────────────────────────
_ORACLE_PARTNERS = [
    ("Infosys Oracle",    "site:infosys.com oracle cloud case study client"),
    ("Wipro Oracle",      "site:wipro.com oracle ERP implementation client"),
    ("Capgemini Oracle",  "site:capgemini.com oracle cloud implementation"),
    ("CGI Oracle",        "site:cgi.com oracle cloud ERP"),
    ("HCL Oracle",        "site:hcltech.com oracle cloud implementation"),
    ("Certus Oracle",     "certus solutions oracle cloud implementation customer"),
    ("Mythics Oracle",    "mythics oracle cloud implementation customer"),
    ("Evosys Oracle",     "evosys oracle cloud implementation case study"),
    ("Namos Oracle",      "namos oracle cloud ERP client"),
    ("Mastek Oracle",     "mastek oracle cloud implementation"),
    ("Keste Oracle",      "keste oracle cloud case study"),
    ("Oracle Partner",    "oracle gold partner ERP implementation success story 2024"),
    ("Oracle Go-Live",    "oracle cloud ERP go-live case study 2024"),
]

# ── JDE specialist SI partners ───────────────────────────────────────────────
_JDE_PARTNERS = [
    # Big SIs with large JDE practices
    ("IBM JDE",               "IBM JD Edwards implementation case study client success"),
    ("IBM JDE Job",           "IBM \"JD Edwards\" OR \"JDE\" consultant client end-user"),
    ("PwC JDE",               "PwC \"JD Edwards\" OR \"JDE\" implementation client case study"),
    ("Deloitte JDE",          "Deloitte \"JD Edwards\" OR \"JDE\" implementation client success"),
    ("Accenture JDE",         "Accenture \"JD Edwards\" OR \"JDE\" implementation client"),
    ("Capgemini JDE",         "Capgemini \"JD Edwards\" OR \"JDE\" case study client"),
    ("Cognizant JDE",         "Cognizant \"JD Edwards\" EnterpriseOne implementation client"),
    ("TCS JDE",               "TCS \"JD Edwards\" OR \"JDE EnterpriseOne\" implementation client"),
    ("NTT Data JDE",          "NTT Data \"JD Edwards\" implementation client success story"),
    ("DXC JDE",               "DXC Technology \"JD Edwards\" client implementation"),
    # Wipro — acquired Edgewater Consulting (historically biggest JDE SI)
    ("Wipro Edgewater JDE",   "Wipro Edgewater \"JD Edwards\" OR \"JDE\" client implementation"),
    ("Wipro JDE",             "site:wipro.com \"JD Edwards\" OR \"JDE\" client case study"),
    # HCL — acquired Ciber's JDE practice
    ("HCL Ciber JDE",         "HCL Ciber \"JD Edwards\" OR \"JDE\" client implementation success"),
    ("HCL JDE",               "site:hcltech.com \"JD Edwards\" OR \"JDE\" client"),
    # Syntax — major JDE managed services & hosting provider
    ("Syntax JDE",            "Syntax \"JD Edwards\" OR \"JDE\" client case study success story"),
    ("Syntax JDE Site",       "site:syntax.com \"JD Edwards\" client implementation"),
    # Denovo — JDE specialist SI
    ("Denovo JDE",            "Denovo consulting \"JD Edwards\" OR \"JDE\" client case study"),
    ("Denovo JDE Site",       "site:denovoconsulting.com JD Edwards client success"),
    # Terillium — JDE specialist
    ("Terillium JDE",         "Terillium \"JD Edwards\" OR \"JDE\" client implementation"),
    ("Terillium JDE Site",    "site:terillium.com JD Edwards client case study"),
    # Steltix — major European JDE partner
    ("Steltix JDE",           "Steltix \"JD Edwards\" OR \"JDE\" client implementation case study"),
    ("Steltix JDE Site",      "site:steltix.com JD Edwards client"),
    # Resolution IT — UK JDE partner
    ("Resolution IT JDE",     "\"Resolution IT\" \"JD Edwards\" client implementation UK"),
    # Collaborate Business Solutions
    ("CBS JDE",               "\"Collaborate Business Solutions\" \"JD Edwards\" client"),
    # Baker Tilly Digital
    ("Baker Tilly JDE",       "\"Baker Tilly\" \"JD Edwards\" OR \"JDE\" client implementation"),
    # Jade Global
    ("Jade Global JDE",       "\"Jade Global\" \"JD Edwards\" OR \"JDE\" client case study"),
    # Hitachi Solutions
    ("Hitachi JDE",           "\"Hitachi Solutions\" \"JD Edwards\" OR \"JDE\" client"),
    # Spinnaker Support — third-party JDE support (knows all JDE clients)
    ("Spinnaker JDE",         "\"Spinnaker Support\" \"JD Edwards\" client success story"),
    ("Spinnaker JDE Site",    "site:spinnakersupport.com JD Edwards client"),
    # Rimini Street — third-party JDE support
    ("Rimini JDE",            "\"Rimini Street\" \"JD Edwards\" OR \"JDE\" client case study"),
    ("Rimini JDE Site",       "site:riministreet.com JD Edwards client success"),
    # Mastek — has JDE practice
    ("Mastek JDE",            "Mastek \"JD Edwards\" OR \"JDE\" client implementation"),
    # Birlasoft — JDE practice
    ("Birlasoft JDE",         "Birlasoft \"JD Edwards\" OR \"JDE\" client case study"),
    # Zensar — JDE practice
    ("Zensar JDE",            "Zensar \"JD Edwards\" OR \"JDE\" client implementation"),
    # eVerge Group
    ("eVerge JDE",            "\"eVerge\" \"JD Edwards\" OR \"JDE\" client case study"),
    # Generic JDE success story searches
    ("JDE Case Study",        "\"JD Edwards\" OR \"JDE EnterpriseOne\" customer success story case study 2024"),
    ("JDE Go-Live",           "\"JD Edwards\" OR \"JDE\" go-live implementation completed client 2024"),
    ("JDE Upgrade",           "\"JD Edwards\" EnterpriseOne upgrade completed client 2024"),
    ("JDE Manufacturing",     "\"JD Edwards\" manufacturing implementation client success"),
    ("JDE Construction",      "\"JD Edwards\" construction homebuilder client implementation"),
    ("JDE Energy",            "\"JD Edwards\" energy utilities client implementation go-live"),
    ("JDE Distribution",      "\"JD Edwards\" distribution logistics client implementation"),
    ("JDE Agriculture",       "\"JD Edwards\" agriculture food beverage client implementation"),
]

# ── Client name extraction patterns ─────────────────────────────────────────
_CLIENT_PATTERNS = [
    # SI helping a named client
    r"(?:helps?|assisted?|enabled?|implemented?\s+for|deployed?\s+for|migrated?\s+(?:to\s+(?:JD\s*Edwards|Oracle)|for))\s+([A-Z][A-Za-z0-9\s&,\.]{2,50}?)(?:\s+(?:to|with|on|achieve|improve|transform|implement))",
    # Client action: selects, goes live, migrates
    r"([A-Z][A-Za-z0-9\s&\.]{3,50}?)\s+(?:goes?\s+live|went\s+live|selected|chose|implemented|deployed|migrated|upgraded?|transforms?)",
    # Labelled: customer/client/organisation
    r"(?:customer|client|organisation|organization)[:\s]+([A-Z][A-Za-z0-9\s&\.]{3,50}?)[\.\,]",
    # Client awards contract / selects partner
    r"([A-Z][A-Za-z0-9\s&\.]{3,50}?)\s+(?:selects?|chooses?|partners?\s+with|awards?\s+contract)",
    # "end client: Company"
    r"end[\s\-]?client[:\s]+([A-Z][A-Za-z0-9\s&',\.]{2,50}?)(?=\s+(?:in|based|is)|\.|,|$)",
    # "for our client, Company"
    r"for\s+(?:our\s+(?:key\s+)?client|a\s+(?:key\s+)?client)[,:\s]+([A-Z][A-Za-z0-9\s&',\.]{2,50}?)(?=\s+(?:in|based|located|is)|\.|,|$)",
    # JDE-specific: "Company upgrades JD Edwards"
    r"([A-Z][A-Za-z0-9\s&\.]{3,50}?)\s+(?:upgrades?|implements?|deploys?|adopts?)\s+(?:JD\s*Edwards|JDE|EnterpriseOne)",
    # JDE-specific: "JD Edwards selected by Company"
    r"(?:JD\s*Edwards|JDE|EnterpriseOne)\s+(?:selected\s+by|implemented\s+at|deployed\s+at|chosen\s+by)\s+([A-Z][A-Za-z0-9\s&\.]{3,50})",
]

# Words that confirm we extracted the SI name, not the end client
_PARTNER_WORDS: set[str] = {
    "accenture", "deloitte", "pwc", "kpmg", "ey", "ernst",
    "ibm", "infosys", "wipro", "hcl", "tcs", "tata",
    "capgemini", "cgi", "ntt", "dxc", "unisys",
    "mastek", "keste", "evosys", "namos", "certus", "mythics",
    "aspire", "oracle", "microsoft", "sap",
    "syntax", "denovo", "terillium", "steltix", "resolution",
    "collaborate", "baker", "jade", "hitachi", "spinnaker",
    "rimini", "birlasoft", "zensar", "mphasis", "cognizant",
    "mindtree", "hexaware", "edgewater", "ciber", "velocity",
    "everge", "lortek", "xtend", "astute",
}


def _extract_client(title: str, desc: str) -> str:
    for pat in _CLIENT_PATTERNS:
        for text in (title, desc):
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                candidate = m.group(1).strip().rstrip(".,;:")
                if candidate.lower().split()[0] in _PARTNER_WORDS:
                    continue
                if is_valid_company_name(candidate) and len(candidate) > 3:
                    return candidate
    return ""


class PartnerCaseStudySignal(BaseSignal):
    source_name = "partner_casestudy"

    def fetch(self, query: str = "", location: str = "", max_pages: int = None) -> list[dict]:
        results = []
        seen = set()

        all_partners = _ORACLE_PARTNERS + _JDE_PARTNERS

        for partner_name, search_query in all_partners:
            loc_suffix = f" {location}" if location else ""
            rss_url = BING_RSS + urllib.parse.quote(search_query + loc_suffix)

            try:
                feed = feedparser.parse(rss_url)
                count = 0

                for entry in feed.entries[:20]:
                    title   = clean_text(entry.get("title", ""))
                    raw_sum = entry.get("summary", "") or entry.get("description", "")
                    desc    = truncate(clean_text(re.sub(r"<[^>]+>", " ", raw_sum)), 500)
                    link    = entry.get("link", "")

                    key = title + link
                    if key in seen:
                        continue
                    seen.add(key)

                    client = _extract_client(title, desc)
                    if not client:
                        continue

                    # Detect if this is a JDE or Oracle Cloud signal
                    combined = f"{title} {desc}".lower()
                    is_jde = any(kw in combined for kw in [
                        "jd edwards", "jde", "enterpriseone", "jde e1",
                    ])
                    product_hint = "JD Edwards" if is_jde else "Oracle (General)"

                    results.append(self._make_signal(
                        company_name=client,
                        job_title=f"{'JDE' if is_jde else 'Oracle'} Implementation — {partner_name}",
                        description=desc or title,
                        url=link,
                        posted_date=entry.get("published", ""),
                        extra={
                            "signal_type": "partner_casestudy",
                            "si_partner": partner_name,
                            "oracle_product_hint": product_hint,
                        },
                    ))
                    count += 1

                logger.info(f"PartnerCaseStudy '{partner_name}' → {count} client signals")
                random_delay(0.5, 1.0)

            except Exception as e:
                logger.error(f"PartnerCaseStudy '{partner_name}': {e}")

        logger.info(f"PartnerCaseStudy total → {len(results)} client signals")
        return results
