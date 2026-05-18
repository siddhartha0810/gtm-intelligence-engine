import re
import time
import random
import logging
from urllib.parse import urlparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def random_delay(min_sec: float = 2.0, max_sec: float = 6.0):
    time.sleep(random.uniform(min_sec, max_sec))


def random_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def extract_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")
        return domain
    except Exception:
        return ""


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def truncate(text: str, max_len: int = 500) -> str:
    if not text:
        return ""
    return text[:max_len] + "..." if len(text) > max_len else text


_INVALID_NAME_STARTS = (
    # question words
    "how ", "why ", "what ", "when ", "where ", "who ", "which ",
    # -ing gerunds
    "making ", "creating ", "building ", "learning ", "getting ",
    "using ", "understanding ", "introducing ", "announcing ",
    "navigating ", "simplifying ", "migrating ", "moving ", "transforming ",
    "modernizing ", "implementing ", "deploying ", "managing ", "driving ",
    "leveraging ", "exploring ", "maximizing ", "optimizing ", "accelerating ",
    "integrating ", "streamlining ", "scaling ", "choosing ", "selecting ",
    "preparing ", "planning ", "enabling ", "unlocking ", "achieving ",
    "delivering ", "helping ", "supporting ", "ensuring ", "reducing ",
    "improving ", "securing ", "protecting ", "automating ", "centralizing ",
    "consolidating ", "replacing ", "upgrading ", "rethinking ", "reimagining ",
    "embracing ", "adopting ", "evaluating ", "comparing ", "connecting ",
    "advancing ", "unifying ", "enhancing ", "positioning ", "powering ",
    # third-person present / past tense verbs
    "announces ", "announced ", "advances ", "achieves ", "unifies ",
    "enhances ", "positions ", "powers ", "drives ", "enables ",
    "launches ", "launches ", "expands ", "transforms ", "selects ",
    "implements ", "deploys ", "migrates ", "adopts ", "completes ",
    "wins ", "lands ", "secures ", "partners ", "signs ", "inks ",
    "delivers ", "deepens ", "deepen ", "embeds ", "helps ",
    "modernizes ", "calls ", "migrate ", "catastrophic ",
    "improves ", "reduces ", "increases ", "generates ", "earns ",
    "reports ", "releases ", "updates ", "reveals ", "targets ",
    "raises ", "cuts ", "boosts ", "grows ", "faces ",
    "introduces ", "showcases ", "shifts ", "uses ", "leverages ",
    "organization ", "accelerate ", "collaborate ", "leading ",
    "expand ", "supports ", "revolutionizes ", "opens ", "at ",
    "provides ",
    # prepositions / filler starters
    "inside ", "behind ", "beyond ", "across ", "through ", "toward ",
    "within ", "between ", "around ", "about ", "after ", "before ",
    # articles / pronouns
    "is ", "are ", "will ", "can ", "should ", "does ", "did ",
    "a ", "an ", "the ", "this ", "these ", "those ",
    # generic adjective starters
    "new ", "next ", "mass ", "channel ", "virtual ", "global ",
    "key ", "major ", "full ", "real ", "open ", "smart ", "fast ",
    "top ", "best ", "make ", "create ", "build ", "learn ", "get ",
)
_INVALID_NAME_FRAGMENTS = (
    "case for", "guide to", "tips for", "best practice",
    "introduction to", "how to", "what is", "why you",
    "business case", "ap automation", "erp project",
    "oracle project", "it project", "cio.com", "forbes",
    "gartner", "techcrunch", "computerworld", "infoworld",
    # Oracle product names that regex picks up as "companies"
    "netsuite next", "autonomous database", "preconfigured database",
    "cloud migration", "sap migration", "mass migration",
    "heterogeneous migration", "virtualization", "cloud infrastructure",
    "digital transformation", "cloud journey", "erp modernization",
    "oracle database", "oracle cloud", "oracle fusion", "oracle erp",
    # headline-style fragments
    "calls out", "selects four", "migrate sap", "announce industry",
    "help their", "helps their", "all industries", "across all",
    "on the promise", "fortify cloud", "customer success services",
    "with netsuite", "ellison", "once again", "four major",
    "downtime migration", "layoff", "go silent", "puts s&p",
    "government departments", "playbooks help", "named a leader",
    "named leader", "wins two", "teams with",
    "linux migration", "zdm migration", "sap vs", " vs ",
    "air force awards", "partner awards", "ways erp",
    "huawei", "'s erp",
)

# Verbs that should never trail a real company name
_TRAILING_VERBS = {
    "announce", "announces", "announced",
    "migrate", "migrates", "migrated",
    "modernize", "modernizes",
    "launch", "launches",
    "select", "selects",
    "deploy", "deploys",
    "release", "releases",
    "update", "updates",
    "report", "reports",
    "help", "helps",
    "expand", "expands",
    "transform", "transforms",
    "collaborate", "collaborates",
    "picks", "named", "automated", "silent",
    "agentic", "analytics",
    "provides", "makes", "successfully", "awards",
    "migrations",
}

# Verbs that indicate a headline when appearing as a non-first interior word
# These are unambiguously verb forms (not plausible as company name words)
_INTERIOR_ACTION_VERBS = {
    "modernizes", "unifies", "digitizes", "centralizes", "standardizes",
    "automates", "optimizes", "streamlines", "accelerates", "consolidates",
    "implements", "deploys", "migrates", "integrates", "upgrades",
    "announces", "launches", "expands", "transforms", "acquires",
    "improves", "reduces", "increases", "delivers", "achieves",
    "collaborates", "introduces", "showcases", "completes", "debuts",
    "accelerate", "revolutionizes", "provides", "makes",
}

# Single generic words that are never company names
_SINGLE_WORD_BLOCKLIST = {
    "announcing", "inside", "virtualization", "migration", "migrations",
    "automation", "modernization", "transformation", "infrastructure",
    "analytics", "integration", "implementation", "deployment",
    "cloud", "database", "enterprise", "solutions", "services",
    "management", "platform", "technology", "technologies",
    "systems", "consulting", "partners", "global", "focus",
    "next", "future", "digital", "innovation", "strategy",
    "approach", "journey", "path", "roadmap", "success", "story",
}


def is_valid_company_name(name: str) -> bool:
    if not name or len(name) < 3 or len(name) > 80:
        return False
    name_l = name.lower().strip()

    # Block single generic words
    if name_l in _SINGLE_WORD_BLOCKLIST:
        return False

    # Block names that are just Oracle product names
    oracle_products = {
        "oracle", "netsuite", "hyperion", "peoplesoft", "siebel",
        "jd edwards", "weblogic", "mysql", "java",
    }
    if name_l in oracle_products:
        return False

    for start in _INVALID_NAME_STARTS:
        if name_l.startswith(start):
            return False
    for fragment in _INVALID_NAME_FRAGMENTS:
        if fragment in name_l:
            return False

    words = name.split()
    if len(words) > 5:
        return False

    # If any word after the first starts with lowercase (excluding prepositions/articles)
    # it's an article title fragment ("Adventist Health unifies systems", "Baylor ignites growth")
    _OK_LOWERCASE = {"of", "and", "the", "at", "by", "for", "in", "on", "to", "a", "an",
                     "de", "van", "von", "du", "la", "le", "los", "las"}
    if len(words) > 1 and any(
        w[0].islower() for w in words[1:]
        if w and w[0].isalpha() and w.lower() not in _OK_LOWERCASE
    ):
        return False

    # Reject if name ends with a bare verb ("Amazon Web Services Announce")
    if words and words[-1].lower() in _TRAILING_VERBS:
        return False

    # Reject if any non-first word is an unambiguous action verb ("Atlanta Modernizes Constituent")
    if len(words) > 1 and any(w.lower() in _INTERIOR_ACTION_VERBS for w in words[1:]):
        return False

    if name_l.rstrip().endswith((" in", " for", " of", " to", " at", " by", " with", " -")):
        return False

    # Reject if every word is a common English noun/verb (no proper noun signal)
    common_words = {
        "migration", "migrations", "transformation", "implementation",
        "deployment", "integration", "automation", "modernization",
        "cloud", "data", "digital", "enterprise", "business",
        "management", "solution", "solutions", "service", "services",
        "system", "systems", "technology", "platform", "focus",
        "channel", "mass", "complex", "simple", "next", "new",
    }
    if words and all(w.lower() in common_words for w in words):
        return False

    return True


def resolve_feed_url(entry) -> str:
    """
    Google News RSS article links are internal redirect URLs that don't open
    in browsers. Try to get the real article URL from the feed entry.
    Priority: entry.source.href → entry.links alternate → entry.link (fallback)
    """
    # Try source href (actual publisher URL)
    source = getattr(entry, "source", {})
    if isinstance(source, dict):
        href = source.get("href", "")
    else:
        href = getattr(source, "href", "")
    if href and "google.com" not in href:
        return href

    # Try alternate links
    for link in getattr(entry, "links", []):
        rel = link.get("rel", "")
        url = link.get("href", "")
        if url and "google.com" not in url and rel in ("alternate", ""):
            return url

    raw = entry.get("link", "") if isinstance(entry, dict) else getattr(entry, "link", "")

    # Google News redirect — attempt a HEAD request to resolve the real URL
    if raw and "news.google.com" in raw:
        try:
            import requests as _req
            resp = _req.head(raw, headers=random_headers(), timeout=5, allow_redirects=True)
            final = resp.url
            if "google.com" not in final:
                return final
        except Exception:
            pass
        return ""  # don't store an unresolvable google.com URL

    return raw or ""
