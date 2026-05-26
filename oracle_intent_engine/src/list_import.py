"""
list_import.py
==============
List Import — CSV/Excel ingestion with field mapping and saved templates.

Workflow:
  1. User uploads CSV/Excel file via POST /api/import/upload
  2. Server parses headers and returns them alongside HubSpot field suggestions
  3. User maps columns → HubSpot fields (optionally saves template)
  4. POST /api/import/process runs ETL: parse → validate → DQE → stage
  5. Staged records flow into companies / company_contacts tables with status='staged'
"""

import csv
import io
import json
import re
from typing import Optional

import openpyxl

import oracle_intent_engine.src.database as db
from oracle_intent_engine.src.data_quality import run_dqe_on_company, run_dqe_on_contact

# ── HubSpot field definitions (single source of truth) ───────────────────────

HS_COMPANY_FIELDS = [
    {"key": "name",                       "label": "Company Name",               "required": True},
    {"key": "domain",                     "label": "Website / Domain",           "required": False},
    {"key": "phone",                      "label": "Phone",                      "required": False},
    {"key": "industry",                   "label": "Industry",                   "required": False},
    {"key": "number_of_employees",        "label": "Number of Employees",        "required": False},
    {"key": "about_us",                   "label": "About Us",                   "required": False},
    {"key": "billing_street",             "label": "Billing Street",             "required": False},
    {"key": "billing_city",               "label": "Billing City",               "required": False},
    {"key": "billing_state",              "label": "Billing State",              "required": False},
    {"key": "billing_postal_code",        "label": "Billing Postal Code",        "required": False},
    {"key": "billing_country",            "label": "Billing Country",            "required": False},
    {"key": "duns_number",                "label": "DUNS Number",                "required": False},
    {"key": "holding_type",               "label": "Holding Type",               "required": False},
    {"key": "number_of_locations",        "label": "Number of Locations",        "required": False},
    {"key": "oracle_cloud_solutions",     "label": "Oracle Cloud Solutions",     "required": False},
    {"key": "oracle_on_premise_solutions","label": "Oracle On-Premise Solutions","required": False},
    {"key": "oracle_relationship_type",   "label": "Oracle Relationship Type",   "required": False},
    {"key": "oracle_support_end_date",    "label": "Oracle Support End Date",    "required": False},
    {"key": "oracle_version",             "label": "Oracle Version",             "required": False},
    {"key": "number_of_oracle_users",     "label": "Number of Oracle Users",     "required": False},
    {"key": "inoapps_account_manager",    "label": "Inoapps Account Manager",    "required": False},
    {"key": "inoapps_account_tier",       "label": "Inoapps Account Tier",       "required": False},
    {"key": "inoapps_relationship_type",  "label": "Inoapps Relationship Type",  "required": False},
    {"key": "inoapps_services_summary",   "label": "Inoapps Services Summary",   "required": False},
    {"key": "location",                   "label": "Location",                   "required": False},
    {"key": "size",                       "label": "Size / Revenue Band",        "required": False},
    {"key": "target_product",             "label": "Target Oracle Product",      "required": False},
]

HS_CONTACT_FIELDS = [
    {"key": "first_name",      "label": "First Name",       "required": True},
    {"key": "last_name",       "label": "Last Name",        "required": True},
    {"key": "email",           "label": "Email",            "required": False},
    {"key": "phone",           "label": "Phone",            "required": False},
    {"key": "mobile_phone",    "label": "Mobile Phone",     "required": False},
    {"key": "title",           "label": "Job Title",        "required": False},
    {"key": "job_function",    "label": "Job Function",     "required": False},
    {"key": "level",           "label": "Level / Seniority","required": False},
    {"key": "linkedin_url",    "label": "LinkedIn URL",     "required": False},
    {"key": "city",            "label": "City",             "required": False},
    {"key": "state",           "label": "State / Region",   "required": False},
    {"key": "country",         "label": "Country",          "required": False},
    {"key": "salutation",      "label": "Salutation",       "required": False},
    {"key": "suffix",          "label": "Suffix",           "required": False},
    {"key": "do_not_call",     "label": "Do Not Call",      "required": False},
    {"key": "do_not_email",    "label": "Do Not Email",     "required": False},
    {"key": "oracle_alignment", "label": "Oracle Alignment","required": False},
    {"key": "oracle_department","label": "Oracle Department","required": False},
    {"key": "oracle_team",     "label": "Oracle Team",      "required": False},
    {"key": "company_name",    "label": "Company Name",     "required": False},
]

_FIELD_LISTS = {
    "company":      HS_COMPANY_FIELDS,
    "contact":      HS_CONTACT_FIELDS,
}


def _fuzzy_suggest(header: str, entity_type: str) -> Optional[str]:
    """Auto-suggest a HubSpot field key from a CSV column header."""
    fields = _FIELD_LISTS.get(entity_type.lower(), [])
    h = re.sub(r"[^a-z0-9]", "", header.lower())
    best, best_score = None, 0
    for f in fields:
        label_clean = re.sub(r"[^a-z0-9]", "", f["label"].lower())
        key_clean   = re.sub(r"[^a-z0-9]", "", f["key"].lower())
        score = 0
        if h == key_clean or h == label_clean:
            score = 100
        elif h in key_clean or key_clean in h:
            score = 80
        elif h in label_clean or label_clean in h:
            score = 60
        if score > best_score:
            best, best_score = f["key"], score
    return best if best_score >= 60 else None


# ── Mapping templates ─────────────────────────────────────────────────────────

def list_templates(entity_type: str = "") -> list:
    with db.db_cursor(commit=False) as cur:
        if entity_type:
            cur.execute(
                "SELECT * FROM import_mapping_templates WHERE entity_type=%s ORDER BY name",
                (entity_type,),
            )
        else:
            cur.execute("SELECT * FROM import_mapping_templates ORDER BY entity_type, name")
        return [dict(r) for r in cur.fetchall()]


def save_template(name: str, entity_type: str, mappings: dict, user_id: int = None) -> dict:
    with db.db_cursor() as cur:
        cur.execute(
            """INSERT INTO import_mapping_templates (name, entity_type, mappings, created_by)
               VALUES (%s,%s,%s,%s)
               ON CONFLICT (name, entity_type) DO UPDATE SET
                   mappings = EXCLUDED.mappings, updated_at = NOW()
               RETURNING *""",
            (name, entity_type, json.dumps(mappings), user_id),
        )
        return dict(cur.fetchone())


def delete_template(template_id: int) -> bool:
    with db.db_cursor() as cur:
        cur.execute(
            "DELETE FROM import_mapping_templates WHERE id=%s RETURNING id", (template_id,)
        )
        return cur.fetchone() is not None


# ── CSV parsing ───────────────────────────────────────────────────────────────

def _is_xlsx(content: bytes) -> bool:
    """Detect Excel .xlsx by its PK zip magic bytes."""
    return content[:4] == b"PK\x03\x04"


def _parse_xlsx_headers(content: bytes) -> list:
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    headers = []
    for row in ws.iter_rows(min_row=1, max_row=1, values_only=True):
        headers = [str(c).strip() if c is not None else "" for c in row]
        break
    wb.close()
    return [h for h in headers if h]


def _parse_xlsx_rows(content: bytes) -> list:
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        wb.close()
        return []
    headers = [str(c).strip() if c is not None else "" for c in header_row]
    result = []
    for row in rows_iter:
        record = {}
        for col, val in zip(headers, row):
            if col:
                record[col] = str(val).strip() if val is not None else ""
        result.append(record)
    wb.close()
    return result


def parse_csv_headers(content: bytes, entity_type: str) -> dict:
    """
    Parse a CSV or Excel (.xlsx) file and return:
      headers      — list of {csv_header, suggested_field} for the frontend mapping UI
      record_count — number of data rows (excluding header)
      fields       — available HubSpot field definitions
    """
    et = entity_type.lower()
    if _is_xlsx(content):
        raw_headers = _parse_xlsx_headers(content)
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        record_count = max(0, ws.max_row - 1) if ws.max_row else 0
        wb.close()
    else:
        text = content.decode("utf-8-sig", errors="replace")
        lines = [l for l in io.StringIO(text)]
        record_count = max(0, len(lines) - 1)
        reader = csv.reader(io.StringIO(text))
        try:
            raw_headers = next(reader)
        except StopIteration:
            raw_headers = []

    if not raw_headers:
        return {"headers": [], "record_count": 0, "fields": _FIELD_LISTS.get(et, [])}

    headers = []
    for h in raw_headers:
        h = h.strip()
        if not h:
            continue
        suggested = _fuzzy_suggest(h, et)
        headers.append({"csv_header": h, "suggested_field": suggested or ""})

    return {
        "headers":      headers,
        "record_count": record_count,
        "fields":       _FIELD_LISTS.get(et, []),
    }


def process_import(
    content: bytes,
    entity_type: str,
    mappings: dict,
    batch_id: int,
    user_id: int = None,
    default_product: str = "",
) -> dict:
    """
    Run the ETL pipeline for an uploaded CSV.
    mappings = { "CSV Column Header": "hs_field_key", ... }

    Returns { success_count, error_count, errors[] }
    """
    if _is_xlsx(content):
        rows = _parse_xlsx_rows(content)
    else:
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)

    success, errors = 0, []

    for idx, row in enumerate(rows, start=2):
        # Map CSV columns → HubSpot fields
        record: dict = {}
        for csv_col, hs_key in mappings.items():
            val = row.get(csv_col, "").strip()
            if val:
                record[hs_key] = val

        try:
            if entity_type == "company":
                if default_product and not record.get("target_product"):
                    record["target_product"] = default_product
                _import_company(record, user_id)
            elif entity_type == "contact":
                _import_contact(record, user_id)
            success += 1
        except Exception as e:
            errors.append({"row": idx, "error": str(e), "data": record})

    # Update batch stats
    with db.db_cursor() as cur:
        cur.execute(
            """UPDATE import_batches
               SET status='completed', success_count=%s, error_count=%s,
                   error_log=%s, completed_at=NOW()
               WHERE id=%s""",
            (success, len(errors), json.dumps(errors), batch_id),
        )

    return {"success_count": success, "error_count": len(errors), "errors": errors[:50]}


def _import_company(record: dict, user_id: int = None) -> None:
    name = record.get("name", "").strip()
    if not name:
        raise ValueError("Company name is required")

    # DQE check before insert
    issues = run_dqe_on_company(record)
    critical = [i for i in issues if i["severity"] == "critical"]
    if critical:
        raise ValueError(f"DQE: {critical[0]['message']}")

    with db.db_cursor() as cur:
        cur.execute(
            """INSERT INTO companies
                   (name, domain, industry, size, location, phone,
                    number_of_employees, billing_city, billing_country,
                    oracle_relationship_type, oracle_version,
                    inoapps_account_manager, inoapps_account_tier,
                    target_product, source, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'apollo','staged')
               ON CONFLICT (name) DO UPDATE SET
                   domain = COALESCE(EXCLUDED.domain, companies.domain),
                   industry = COALESCE(EXCLUDED.industry, companies.industry),
                   target_product = CASE WHEN EXCLUDED.target_product <> '' THEN EXCLUDED.target_product ELSE companies.target_product END,
                   last_updated = NOW()""",
            (
                name,
                record.get("domain") or None,   # nullable
                record.get("industry") or None,  # nullable
                record.get("size") or None,      # nullable
                record.get("location") or None,  # nullable
                record.get("phone") or "",
                record.get("number_of_employees") or None,  # nullable integer
                record.get("billing_city") or "",
                record.get("billing_country") or "",
                record.get("oracle_relationship_type") or "",
                record.get("oracle_version") or "",
                record.get("inoapps_account_manager") or "",
                record.get("inoapps_account_tier") or "",
                record.get("target_product") or "",
            ),
        )


def _import_contact(record: dict, user_id: int = None) -> None:
    first = record.get("first_name", "").strip()
    last  = record.get("last_name", "").strip()
    if not first or not last:
        raise ValueError("First name and last name are required")

    issues = run_dqe_on_contact(record)
    critical = [i for i in issues if i["severity"] == "critical"]
    if critical:
        raise ValueError(f"DQE: {critical[0]['message']}")

    # Find or create company
    company_name = record.get("company_name", "").strip()
    company_id = None
    if company_name:
        with db.db_cursor() as cur:
            cur.execute(
                "INSERT INTO companies (name, source, status) VALUES (%s,'apollo','staged') "
                "ON CONFLICT (name) DO UPDATE SET last_updated=NOW() RETURNING id",
                (company_name,),
            )
            company_id = cur.fetchone()["id"]

    full_name = f"{first} {last}".strip()
    with db.db_cursor() as cur:
        cur.execute(
            """INSERT INTO company_contacts
                   (company_id, first_name, last_name, full_name, title, email, phone,
                    mobile_phone, linkedin_url, city, state, country,
                    job_function, level, oracle_alignment, oracle_department,
                    oracle_team, source, email_validation_status, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'apollo','valid','staged')
               ON CONFLICT DO NOTHING""",
            (
                company_id, first, last, full_name,
                record.get("title"), record.get("email"),
                record.get("phone"), record.get("mobile_phone"),
                record.get("linkedin_url"), record.get("city"),
                record.get("state"), record.get("country"),
                record.get("job_function"), record.get("level"),
                record.get("oracle_alignment"), record.get("oracle_department"),
                record.get("oracle_team"),
            ),
        )


def create_batch(file_name: str, entity_type: str, record_count: int,
                 template_id: int = None, user_id: int = None) -> dict:
    with db.db_cursor() as cur:
        cur.execute(
            """INSERT INTO import_batches
                   (file_name, entity_type, mapping_template_id, record_count, created_by)
               VALUES (%s,%s,%s,%s,%s) RETURNING *""",
            (file_name, entity_type, template_id, record_count, user_id),
        )
        return dict(cur.fetchone())


def list_batches(limit: int = 50) -> list:
    with db.db_cursor(commit=False) as cur:
        cur.execute(
            """SELECT ib.*, imt.name AS template_name, u.email AS created_by_email
               FROM import_batches ib
               LEFT JOIN import_mapping_templates imt ON imt.id = ib.mapping_template_id
               LEFT JOIN users u ON u.id = ib.created_by
               ORDER BY ib.created_at DESC
               LIMIT %s""",
            (min(limit, 200),),
        )
        return [dict(r) for r in cur.fetchall()]
