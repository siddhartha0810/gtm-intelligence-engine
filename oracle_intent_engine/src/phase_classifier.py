"""
Classifies a raw signal (job posting, news article) into:
  - oracle_product  : which Oracle product is involved
  - phase           : where the company is in its Oracle journey
  - confidence      : 0.0 – 1.0
"""

from src.utils import clean_text

ORACLE_PRODUCTS = {
    "Oracle Cloud ERP": [
        "oracle cloud erp", "oracle fusion erp", "oracle erp cloud",
        "fusion financials", "oracle financials cloud", "oracle general ledger",
        "oracle accounts payable", "oracle accounts receivable",
        "oracle procurement cloud", "oracle fusion financials",
        "oracle project costing", "oracle fixed assets",
    ],
    "Oracle HCM": [
        "oracle hcm", "oracle human capital management", "oracle hcm cloud",
        "fusion hcm", "oracle global hr", "oracle payroll cloud",
        "oracle talent management", "oracle workforce management",
        "oracle absence management", "oracle benefits cloud",
        "oracle recruiting cloud", "oracle learning cloud",
    ],
    "Oracle SCM": [
        "oracle scm", "oracle supply chain", "oracle scm cloud",
        "oracle inventory cloud", "oracle order management cloud",
        "oracle manufacturing cloud", "oracle planning cloud scm",
        "oracle warehouse management", "oracle logistics cloud",
    ],
    "Oracle EPM": [
        "oracle epm", "oracle hyperion", "oracle planning cloud",
        "oracle essbase", "oracle fccs", "oracle financial consolidation",
        "oracle account reconciliation", "oracle narrative reporting",
        "oracle profitability", "oracle epbcs",
    ],
    "Oracle CX": [
        "oracle cx", "oracle sales cloud", "oracle service cloud",
        "oracle marketing cloud", "oracle cpq", "oracle commerce cloud",
        "oracle field service", "oracle configure price quote",
        "oracle subscription management",
    ],
    "NetSuite": [
        "netsuite", "oracle netsuite", "netsuite erp",
        "netsuite implementation", "netsuite administrator",
        "netsuite developer", "netsuite consultant",
    ],
    "Oracle OCI": [
        "oracle cloud infrastructure", " oci ", "oci architect",
        "oracle iaas", "oracle paas", "oracle cloud platform",
        "oracle autonomous", "oracle exadata cloud",
        "oracle cloud migration", "lift and shift oracle",
    ],
    "Oracle Database": [
        "oracle database", "oracle dba", "oracle db ",
        "oracle autonomous database", "oracle exadata",
        "oracle 19c", "oracle 21c", "oracle rac",
        "oracle data guard", "oracle goldengate",
    ],
    "Oracle Integration": [
        "oracle integration cloud", " oic ", "oracle middleware",
        "oracle soa suite", "oracle mft", "oracle api gateway",
        "oracle service bus", "oracle b2b",
    ],
    "Oracle APEX": [
        "oracle apex", "oracle application express", "apex developer",
    ],
    "JD Edwards": [
        "jd edwards", "jde", "jd edwards enterpriseone", "jde enterpriseone",
        "jde e1", "jde oneworld", "jd edwards oneworld", "jdedwards",
        "jde technical developer", "jde functional consultant",
        "jde cnc", "jde cnc administrator", "jde basis administrator",
        "jde orchestrator", "jde tools administrator", "jde system administrator",
        "jde architect", "jde integration", "jde finance consultant",
        "jde manufacturing consultant", "jde distribution consultant",
        "jde hr consultant", "jde payroll", "jde project costing",
        "jde support analyst", "jde security administrator",
        "jde report developer", "jde data migration", "jde analytics",
        "jde business analyst", "jde solution architect", "jde project manager",
        "jde upgrade", "jde implementation", "jde e900", "jde e812",
        "enterpriseone", "e1 developer", "e1 consultant",
    ],
}

PHASE_CONFIG = {
    "researching": {
        "weight": 1,
        "title_kw": [
            "business analyst", "solution architect", "pre-sales",
            "advisory", "strategy", "enterprise architect",
        ],
        "desc_kw": [
            "evaluating", "assessment", "exploring", "research",
            "considering", "requirements gathering", "fit gap analysis",
            "current state", "future state", "roadmap", "feasibility",
            "needs analysis", "landscape assessment",
        ],
    },
    "evaluating": {
        "weight": 2,
        "title_kw": [
            "pre-sales consultant", "solution architect", "functional lead",
            "bid manager", "rfp",
        ],
        "desc_kw": [
            "proof of concept", "poc", "pilot", "rfp", "rfi",
            "shortlist", "vendor selection", "demo", "evaluation criteria",
            "comparing solutions", "due diligence", "selection process",
            "vendor assessment",
        ],
    },
    "budgeting": {
        "weight": 2,
        "title_kw": [
            "project manager", "program director", "vp", "cio",
            "chief information", "director of it", "procurement",
        ],
        "desc_kw": [
            "business case", "budget", "roi", "investment",
            "cost benefit", "approval", "financial justification",
            "capital expenditure", "opex", "capex", "funding",
            "financial planning", "cost analysis",
        ],
    },
    "hiring": {
        "weight": 3,
        "title_kw": [
            "consultant", "administrator", "developer", "analyst",
            "architect", "specialist", "lead", "expert", "manager",
            "functional consultant", "technical consultant",
            "implementation consultant",
        ],
        "desc_kw": [
            "new implementation", "greenfield", "fresh implementation",
            "join our team", "immediate start", "contract", "permanent",
            "full time", "looking for", "seeking experienced",
        ],
    },
    "implementing": {
        "weight": 4,
        "title_kw": [
            "implementation consultant", "project manager",
            "change management", "deployment lead", "cutover manager",
            "integration developer", "data migration",
        ],
        "desc_kw": [
            "implementation", "go-live", "deployment", "migration",
            "rollout", "configure", "customization", "data migration",
            "cutover", "uat", "user acceptance testing", "system integration",
            "parallel run", "sprint", "workstream", "blueprint",
            "realization", "go live support",
        ],
    },
    "post_live": {
        "weight": 2,
        "title_kw": [
            "application support", "functional support",
            "system administrator", "production support",
            "support analyst", "enhancement analyst",
        ],
        "desc_kw": [
            "post-implementation", "post go-live", "hypercare",
            "stabilization", "optimization", "end user support",
            "production support", "break fix", "continuous improvement",
            "managed services", "application managed services",
        ],
    },
}

PHASE_LABELS = {
    "researching":  "Researching",
    "evaluating":   "Evaluating",
    "budgeting":    "Budgeting / Approving",
    "hiring":       "Hiring for Oracle",
    "implementing": "Implementing",
    "post_live":    "Post Go-Live / Support",
}

PHASE_COLORS = {
    "researching":  "#6c757d",
    "evaluating":   "#0d6efd",
    "budgeting":    "#ffc107",
    "hiring":       "#198754",
    "implementing": "#dc3545",
    "post_live":    "#0dcaf0",
}


def detect_oracle_product(title: str, description: str) -> tuple[str, float]:
    combined = f"{title} {description}".lower()
    best_product = "Oracle (General)"
    best_score = 0

    for product, keywords in ORACLE_PRODUCTS.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score > best_score:
            best_score = score
            best_product = product

    confidence = min(best_score / 3.0, 1.0) if best_score > 0 else 0.3
    return best_product, confidence


def detect_phase(title: str, description: str) -> tuple[str, float]:
    title_l = title.lower() if title else ""
    desc_l = description.lower() if description else ""

    phase_scores: dict[str, float] = {}

    for phase, cfg in PHASE_CONFIG.items():
        score = 0.0
        for kw in cfg["title_kw"]:
            if kw in title_l:
                score += 1.5
        for kw in cfg["desc_kw"]:
            if kw in desc_l:
                score += 1.0
        phase_scores[phase] = score * cfg["weight"]

    if not any(v > 0 for v in phase_scores.values()):
        return "hiring", 0.4

    best_phase = max(phase_scores, key=phase_scores.get)
    total = sum(phase_scores.values())
    confidence = round(phase_scores[best_phase] / total, 2) if total else 0.4
    return best_phase, min(confidence, 1.0)


def classify(title: str, description: str, source: str = "") -> dict:
    title = clean_text(title)
    description = clean_text(description)

    product, prod_conf = detect_oracle_product(title, description)
    phase, phase_conf = detect_phase(title, description)

    combined_confidence = round((prod_conf + phase_conf) / 2, 2)

    return {
        "oracle_product": product,
        "phase": phase,
        "phase_label": PHASE_LABELS.get(phase, phase),
        "confidence": combined_confidence,
    }
