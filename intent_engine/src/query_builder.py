"""
query_builder.py
================
Universal intent signal query generator.

Takes a list of target keywords (any product, technology, or topic) and
produces job-board search queries and news queries that will surface
companies showing buying/implementation intent for those keywords.

This replaces the hardcoded QUERIES_BY_PRODUCT and NEWS_QUERIES in config.py
for campaign-driven scans. Oracle campaigns still use the handcrafted queries;
all other campaigns use this builder.

Usage:
    from src.query_builder import build_job_queries, build_news_queries, build_all

    queries = build_all(
        keywords=["Salesforce", "SFDC", "Salesforce CRM"],
        extra_suffixes=["revenue operations"],   # optional
        location_hint="United States",
    )
    # → {"job_queries": [...], "news_queries": [...]}
"""

from __future__ import annotations

# ── Universal job-board query suffixes ───────────────────────────────────────
# Crossing these with any target keyword produces high-signal job queries.
# Ordered by signal strength (strongest intent first).

JOB_SUFFIXES_TIER1 = [
    # Implementation signals — strongest buying intent
    "implementation consultant",
    "implementation manager",
    "implementation project manager",
    "implementation lead",
    "go-live project manager",
    # Administration — already live, expansion opportunity
    "administrator",
    "system administrator",
    "systems administrator",
    # Technical — active build-out
    "technical consultant",
    "developer",
    "technical developer",
    # Functional — business-side implementation
    "functional consultant",
    "business analyst",
    "solution architect",
]

JOB_SUFFIXES_TIER2 = [
    # Migration — high intent, switching from competitor
    "migration consultant",
    "migration project manager",
    "upgrade consultant",
    "cloud migration",
    # Support — existing install base
    "support analyst",
    "support consultant",
    # General
    "consultant",
    "project manager",
    "manager",
    "analyst",
    "specialist",
    "engineer",
]

NEWS_TEMPLATES = [
    # Completion / go-live (highest confidence)
    "go live",
    "goes live",
    "implementation go live",
    "implementation completed",
    "deployment complete",
    "successfully implemented",
    # Selection / procurement
    "company selects",
    "selects for implementation",
    "selects as partner",
    "announces partnership",
    "digital transformation",
    # Migration
    "migrates to",
    "migration announcement",
    "replaces legacy system",
    # Press release patterns
    "implementation announcement",
    "deploys",
    "rolls out",
    "press release implementation",
]

# Role suffixes that signal an END-USER company (not a consultancy)
# Used to weight results — companies hiring these roles are buyers, not SIs
BUYER_SIGNAL_SUFFIXES = [
    "director",
    "vp",
    "vice president",
    "head of",
    "internal",
    "in-house",
    "enterprise",
]


def build_job_queries(
    keywords: list[str],
    extra_suffixes: list[str] | None = None,
    tier: int = 1,
) -> list[str]:
    """
    Generate job-board search queries from target keywords.

    Args:
        keywords:       Target keywords, e.g. ["Salesforce", "SFDC"]
        extra_suffixes: Additional role suffixes to append
        tier:           1 = high-signal suffixes only, 2 = all suffixes

    Returns:
        Deduplicated list of query strings ready for job-board scrapers.
    """
    suffixes = list(JOB_SUFFIXES_TIER1)
    if tier >= 2:
        suffixes += JOB_SUFFIXES_TIER2
    if extra_suffixes:
        suffixes += [s.strip() for s in extra_suffixes if s.strip()]

    seen: set[str] = set()
    queries: list[str] = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        for suffix in suffixes:
            q = f"{kw} {suffix}"
            if q not in seen:
                seen.add(q)
                queries.append(q)

    return queries


def build_news_queries(
    keywords: list[str],
    extra_templates: list[str] | None = None,
) -> list[str]:
    """
    Generate news search queries from target keywords.

    Args:
        keywords:         Target keywords
        extra_templates:  Additional news query templates

    Returns:
        Deduplicated list of query strings for news scrapers.
    """
    templates = list(NEWS_TEMPLATES)
    if extra_templates:
        templates += [t.strip() for t in extra_templates if t.strip()]

    seen: set[str] = set()
    queries: list[str] = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        for tmpl in templates:
            q = f"{kw} {tmpl}"
            if q not in seen:
                seen.add(q)
                queries.append(q)

    return queries


def build_all(
    keywords: list[str],
    extra_suffixes: list[str] | None = None,
    extra_news_templates: list[str] | None = None,
    tier: int = 1,
    max_job_queries: int = 200,
    max_news_queries: int = 60,
) -> dict:
    """
    Build the full query set for a campaign scan.

    Returns:
        {
            "job_queries":  [...],   # for job-board signals
            "news_queries": [...],   # for news signal
        }
    """
    job_queries  = build_job_queries(keywords, extra_suffixes, tier)[:max_job_queries]
    news_queries = build_news_queries(keywords, extra_news_templates)[:max_news_queries]
    return {"job_queries": job_queries, "news_queries": news_queries}


def estimate_query_count(keywords: list[str], tier: int = 1) -> dict:
    """Return how many queries would be generated without building them."""
    suffix_count = len(JOB_SUFFIXES_TIER1)
    if tier >= 2:
        suffix_count += len(JOB_SUFFIXES_TIER2)
    kw_count = len([k for k in keywords if k.strip()])
    return {
        "keywords": kw_count,
        "job_queries": kw_count * suffix_count,
        "news_queries": kw_count * len(NEWS_TEMPLATES),
        "total": kw_count * (suffix_count + len(NEWS_TEMPLATES)),
    }
