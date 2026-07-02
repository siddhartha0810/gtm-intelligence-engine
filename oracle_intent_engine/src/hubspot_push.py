"""
hubspot_push.py
===============
Production-grade HubSpot push/pull using domain-based upsert.
Implements doc §6.2 — company push and contact push patterns.
"""

import json
import os
import secrets
from typing import Optional
import httpx


def _gen_unique_key() -> str:
    """64-char URL-safe unique key (doc §6.1 — nanoid equivalent)."""
    return secrets.token_urlsafe(48)

# ── Field maps (doc §6.1) ─────────────────────────────────────────────────────

HS_COMPANY_FIELD_MAP = {
    # Standard
    "name":                      "name",
    "website":                   "website",
    "domain":                    "domain",
    "phone":                     "phone",
    "industry":                  "industry",
    "number_of_employees":       "numberofemployees",
    "about_us":                  "about_us",
    # Billing
    "billing_street":            "address",
    "billing_city":              "city",
    "billing_state":             "state",
    "billing_postal_code":       "zip",
    "billing_country":           "country",
    # Firmographics
    "duns_number":               "duns_number",
    "holding_type":              "holding_type",
    "number_of_locations":       "number_of_locations",
    # Product / Technology Intel
    "detected_products":         "detected_products",       # comma-separated detected product names
    "vendor_relationship_type":  "vendor_relationship_type",# prospect / customer / partner
    "product_version":           "product_version",
    "target_product":            "target_product",
    # technology_profile resolved at push-time (see _build_company_payload)
    "_technology_profile_name":  "technology_profile",
    # Intent intelligence — auto-computed at push time
    "why_now_reason":            "why_now_reason",       # 1-sentence urgency rationale
    "signal_tier":               "signal_tier",          # P0 / P1 / P2
    "intent_score":              "intent_score",         # 0.0-1.0
    "fit_score":                 "fit_score",            # 0.0-1.0
    "routing":                   "routing",              # ACTIVATE / NURTURE / MONITOR / DISQUALIFY
    "priority_score":            "priority_score",       # 0-100
    "campaign_name":             "intent_campaign_name", # which signal campaign found this company
}

HS_CONTACT_FIELD_MAP = {
    # Core Identity
    "salutation":    "salutation",
    "first_name":    "firstname",
    "last_name":     "lastname",
    "suffix":        "suffix",
    "email":         "email",
    "phone":         "phone",
    "mobile_phone":  "mobilephone",
    "title":         "jobtitle",
    "job_function":  "job_function",
    "level":         "level",
    "linkedin_url":  "linkedinbio",
    "company_name":  "company",
    # Location
    "city":          "city",
    "state":         "state",
    "country":       "country",
    # Consent
    "do_not_call":   "hs_legal_basis",
    "do_not_email":  "hs_email_optout",
    # Data Management
    "creation_source":  "lead_source",
    "person_has_moved": "person_has_moved",
    # Intent enrichment
    "product_alignment":  "product_alignment",   # which product this contact is aligned to
    "ready_for_outreach": "ready_for_outreach",  # ZeroBounce validated
    "signal_tier":        "signal_tier",          # inherited from company P0/P1/P2
}


def _get_api_key() -> str:
    import oracle_intent_engine.src.database as db
    cfg = db.get_hubspot_config()
    key = cfg.get("api_key") or os.environ.get("HUBSPOT_API_KEY", "")
    return key


def _resolve_technology_profile_name(record: dict) -> Optional[str]:
    """Look up the technology profile name from technology_profile_id if present."""
    tp_id = record.get("technology_profile_id")
    if not tp_id:
        return None
    try:
        import oracle_intent_engine.src.database as db
        with db.db_cursor(commit=False) as cur:
            cur.execute("SELECT name FROM technology_profiles WHERE id = %s", (tp_id,))
            row = cur.fetchone()
            return row["name"] if row else None
    except Exception:
        return None


def _build_why_now_reason(record: dict) -> str:
    """
    Generate a one-sentence human-readable rationale for why this company
    is a priority right now — based on their top signals.

    Zapier gtm-cheat-codes pattern: surface 'why-now' context in CRM so reps
    don't need to click into the intent tool to understand urgency.

    Example: "Hired 3 JDE CNC admins in 45 days and posted a JD Edwards
    EnterpriseOne go-live press release."
    """
    phase   = record.get("phase") or (record.get("phases") or [""])[0] or ""
    product = record.get("target_product") or record.get("detected_products") or ""
    signals = int(record.get("signal_count") or record.get("signals") or 0)
    sources = record.get("sources") or []
    tier    = record.get("signal_tier") or "P2"

    if not phase:
        return ""

    phase_descriptions = {
        "implementing": f"actively going live on {product}" if product else "actively implementing",
        "evaluating":   f"evaluating {product} or shortlisting vendors" if product else "in active vendor evaluation",
        "hiring":       f"hiring {product} specialists" if product else "actively hiring for this role",
        "budgeting":    f"in budget approval cycle for {product}" if product else "in budget approval cycle",
        "post_live":    f"live on {product} — expansion opportunity" if product else "live, expansion opportunity",
        "researching":  f"researching {product} options" if product else "in early research stage",
        "upgrading":    f"migrating or upgrading {product}" if product else "in upgrade / migration cycle",
        "supporting":   f"running {product} support — renewal window" if product else "in support / renewal cycle",
    }

    phase_desc = phase_descriptions.get(phase, f"showing {phase} signals")
    source_note = f" across {len(sources)} sources" if len(sources) > 1 else ""
    signal_note = f" ({signals} corroborating signals)" if signals >= 3 else ""
    tier_note   = " — P0: act within 48h" if tier == "P0" else (" — P1: act this week" if tier == "P1" else "")

    return f"Company is {phase_desc}{source_note}{signal_note}.{tier_note}".strip()


def _build_company_payload(record: dict) -> dict:
    # Inject resolved technology_profile_name so the field map can pick it up
    enriched = dict(record)
    tp_name = _resolve_technology_profile_name(record)
    if tp_name:
        enriched["_technology_profile_name"] = tp_name

    # Compute why-now reason if not already present
    if not enriched.get("why_now_reason"):
        enriched["why_now_reason"] = _build_why_now_reason(record)

    props = {}
    for db_col, hs_prop in HS_COMPANY_FIELD_MAP.items():
        val = enriched.get(db_col)
        if val is not None and str(val).strip():
            if isinstance(val, list):
                props[hs_prop] = ";".join(str(v) for v in val)
            else:
                props[hs_prop] = str(val).strip()
    return {"properties": props}


def _build_contact_payload(record: dict) -> dict:
    props = {}
    for db_col, hs_prop in HS_CONTACT_FIELD_MAP.items():
        val = record.get(db_col)
        if val is not None and str(val).strip():
            if isinstance(val, bool):
                props[hs_prop] = str(val).lower()
            else:
                props[hs_prop] = str(val).strip()
    return {"properties": props}


async def push_company_to_hubspot(record: dict) -> dict:
    """
    Domain-based upsert per doc §6.2:
    1. Build payload from all 27 fields
    2. Search HubSpot by domain
    3. PATCH if found, POST if not
    4. Return {ok, hubspot_id, action}
    """
    api_key = _get_api_key()
    if not api_key:
        return {"ok": False, "error": "HubSpot API key not configured"}

    payload = _build_company_payload(record)
    domain  = (record.get("domain") or "").strip().lower()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=15) as client:
        existing_id: Optional[str] = None

        # Search by domain
        if domain:
            clean_domain = domain.replace("https://", "").replace("http://", "").lstrip("www.").split("/")[0]
            search_payload = {
                "filterGroups": [{"filters": [{"propertyName": "domain", "operator": "EQ", "value": clean_domain}]}],
                "properties": ["domain", "name"],
                "limit": 1,
            }
            sr = await client.post(
                "https://api.hubapi.com/crm/v3/objects/companies/search",
                json=search_payload, headers=headers,
            )
            if sr.status_code == 200:
                results = sr.json().get("results", [])
                if results:
                    existing_id = results[0]["id"]

        if existing_id:
            r = await client.patch(
                f"https://api.hubapi.com/crm/v3/objects/companies/{existing_id}",
                json=payload, headers=headers,
            )
            action = "updated"
        else:
            r = await client.post(
                "https://api.hubapi.com/crm/v3/objects/companies",
                json=payload, headers=headers,
            )
            action = "created"

        if r.status_code in (200, 201):
            data = r.json()
            return {"ok": True, "hubspot_id": data.get("id"), "action": action}
        return {"ok": False, "error": r.json().get("message", f"HTTP {r.status_code}"), "action": action}


async def push_contact_to_hubspot(record: dict) -> dict:
    """
    Email-based upsert for contacts (mirror of company push).
    Search by email → PATCH if found, POST if not.
    """
    api_key = _get_api_key()
    if not api_key:
        return {"ok": False, "error": "HubSpot API key not configured"}

    payload = _build_contact_payload(record)
    email   = (record.get("email") or "").strip().lower()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=15) as client:
        existing_id: Optional[str] = None

        if email:
            search_payload = {
                "filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}],
                "properties": ["email", "firstname", "lastname"],
                "limit": 1,
            }
            sr = await client.post(
                "https://api.hubapi.com/crm/v3/objects/contacts/search",
                json=search_payload, headers=headers,
            )
            if sr.status_code == 200:
                results = sr.json().get("results", [])
                if results:
                    existing_id = results[0]["id"]

        if existing_id:
            r = await client.patch(
                f"https://api.hubapi.com/crm/v3/objects/contacts/{existing_id}",
                json=payload, headers=headers,
            )
            action = "updated"
        else:
            r = await client.post(
                "https://api.hubapi.com/crm/v3/objects/contacts",
                json=payload, headers=headers,
            )
            action = "created"

        if r.status_code in (200, 201):
            data = r.json()
            return {"ok": True, "hubspot_id": data.get("id"), "action": action}
        return {"ok": False, "error": r.json().get("message", f"HTTP {r.status_code}"), "action": action}


async def bulk_push_companies(status_filter: str = "approved", limit: int = 100) -> dict:
    """Bulk push all companies with given status. Returns per-record results."""
    import oracle_intent_engine.src.database as db
    with db.db_cursor(commit=False) as cur:
        cur.execute(
            "SELECT * FROM companies WHERE status=%s LIMIT %s",
            (status_filter, limit),
        )
        records = [dict(r) for r in cur.fetchall()]

    results = {"total": len(records), "pushed": 0, "updated": 0, "failed": 0, "errors": []}
    for rec in records:
        res = await push_company_to_hubspot(rec)
        if res["ok"]:
            # Update local status and hubspot_id
            with db.db_cursor() as cur:
                cur.execute(
                    "UPDATE companies SET status='pushed_to_hubspot', hubspot_id=%s, last_updated=NOW() WHERE id=%s",
                    (res.get("hubspot_id"), rec["id"]),
                )
            if res["action"] == "created":
                results["pushed"] += 1
            else:
                results["updated"] += 1
        else:
            results["failed"] += 1
            results["errors"].append({"company": rec.get("name"), "error": res.get("error")})
    return results


async def bulk_push_contacts(status_filter: str = "approved", limit: int = 100) -> dict:
    """Bulk push all contacts with given status."""
    import oracle_intent_engine.src.database as db
    with db.db_cursor(commit=False) as cur:
        cur.execute(
            """SELECT cc.*, c.name AS company_name
               FROM company_contacts cc
               JOIN companies c ON c.id = cc.company_id
               WHERE cc.status = %s
               LIMIT %s""",
            (status_filter, limit),
        )
        records = [dict(r) for r in cur.fetchall()]

    results = {"total": len(records), "pushed": 0, "updated": 0, "failed": 0, "errors": []}
    for rec in records:
        res = await push_contact_to_hubspot(rec)
        if res["ok"]:
            with db.db_cursor() as cur:
                cur.execute(
                    "UPDATE company_contacts SET status='pushed_to_hubspot', hubspot_id=%s, hubspot_synced_at=NOW() WHERE id=%s",
                    (res.get("hubspot_id"), rec["id"]),
                )
            if res["action"] == "created":
                results["pushed"] += 1
            else:
                results["updated"] += 1
        else:
            results["failed"] += 1
            results["errors"].append({"contact": f"{rec.get('first_name')} {rec.get('last_name')}", "error": res.get("error")})
    return results


async def sync_pull_from_hubspot(api_key: str) -> dict:
    """
    Pull companies AND contacts from HubSpot into local DB.
    Companies: name, domain, industry, phone, numberOfEmployees
    Contacts: firstname, lastname, email, jobtitle, phone
    """
    import oracle_intent_engine.src.database as db
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    pulled_companies, pulled_contacts, errors = 0, 0, []

    async with httpx.AsyncClient(timeout=30) as client:
        # Pull companies
        try:
            after = None
            while True:
                url = "/crm/v3/objects/companies?limit=100&properties=name,domain,website,industry,phone,numberofemployees,city,country,state,address,zip"
                if after:
                    url += f"&after={after}"
                r = await client.get(f"https://api.hubapi.com{url}", headers=headers)
                if r.status_code != 200:
                    errors.append(f"companies: HTTP {r.status_code}")
                    break
                data = r.json()
                for obj in data.get("results", []):
                    props = obj.get("properties", {})
                    name = (props.get("name") or "").strip()
                    if not name:
                        continue
                    with db.db_cursor() as cur:
                        cur.execute(
                            """INSERT INTO companies
                                   (name, domain, website, industry, phone, number_of_employees,
                                    billing_street, billing_city, billing_country, billing_state,
                                    billing_postal_code,
                                    hubspot_id, hubspot_synced_at, source, status, unique_key)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),'hubspot_pull','approved',%s)
                               ON CONFLICT (name) DO UPDATE SET
                                   hubspot_id    = EXCLUDED.hubspot_id,
                                   domain        = COALESCE(EXCLUDED.domain,   companies.domain),
                                   website       = COALESCE(EXCLUDED.website,  companies.website),
                                   industry      = COALESCE(EXCLUDED.industry, companies.industry),
                                   unique_key    = CASE
                                       WHEN companies.unique_key = '' THEN EXCLUDED.unique_key
                                       ELSE companies.unique_key
                                   END,
                                   hubspot_synced_at = NOW(),
                                   last_updated  = NOW()""",
                            (name, props.get("domain"), props.get("website"),
                             props.get("industry"), props.get("phone"),
                             int(props["numberofemployees"]) if props.get("numberofemployees") else None,
                             props.get("address"), props.get("city"), props.get("country"),
                             props.get("state"), props.get("zip"),
                             str(obj["id"]), _gen_unique_key()),
                        )
                    pulled_companies += 1
                paging = data.get("paging", {})
                after = paging.get("next", {}).get("after")
                if not after:
                    break
        except Exception as e:
            errors.append(f"companies pull: {e}")

        # Pull contacts
        try:
            after = None
            while True:
                url = "/crm/v3/objects/contacts?limit=100&properties=firstname,lastname,email,jobtitle,phone,mobilephone,city,state,country"
                if after:
                    url += f"&after={after}"
                r = await client.get(f"https://api.hubapi.com{url}", headers=headers)
                if r.status_code != 200:
                    errors.append(f"contacts: HTTP {r.status_code}")
                    break
                data = r.json()
                for obj in data.get("results", []):
                    props = obj.get("properties", {})
                    first = (props.get("firstname") or "").strip()
                    last  = (props.get("lastname")  or "").strip()
                    if not first and not last:
                        continue
                    with db.db_cursor() as cur:
                        cur.execute(
                            """INSERT INTO company_contacts
                                   (first_name, last_name, title, email, phone, mobile_phone,
                                    city, state, country,
                                    hubspot_id, hubspot_synced_at, source, status, unique_key)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),'hubspot_pull','approved',%s)
                               ON CONFLICT DO NOTHING""",
                            (first, last, props.get("jobtitle"), props.get("email"),
                             props.get("phone"), props.get("mobilephone"),
                             props.get("city"), props.get("state"), props.get("country"),
                             str(obj["id"]), _gen_unique_key()),
                        )
                    pulled_contacts += 1
                paging = data.get("paging", {})
                after = paging.get("next", {}).get("after")
                if not after:
                    break
        except Exception as e:
            errors.append(f"contacts pull: {e}")

    db.update_hubspot_sync_status("success" if not errors else "error",
                                   pulled_companies, pulled_contacts)
    return {"companies": pulled_companies, "contacts": pulled_contacts, "errors": errors}
