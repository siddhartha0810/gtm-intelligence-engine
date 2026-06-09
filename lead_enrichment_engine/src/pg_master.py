"""
pg_master.py
============
Read-only interface to contacts_master (Salesforce CRM export).

contacts_master is a pre-existing table in Inoapps-Data-DB — it is
populated by Salesforce exports and is never written to by this pipeline.

All write operations (upsert_master_leads) are no-ops.
All read operations query contacts_master with correct Salesforce column names.

Column mapping (Salesforce → PostgreSQL lowercase):
  FirstName               → firstname
  LastName                → lastname
  Title                   → title
  Email                   → email
  Validated_Email         → validated_email
  ZB_Valid_Email          → zb_valid_email  (Yes/No flag — filter = 'Yes')
  Validated_Email_Status  → validated_email_status
  LinkedIn_URL__c         → linkedin_url__c
  LinkedIn_URL_Enriched   → linkedin_url_enriched
  New_Company             → new_company
  Existing_Company        → existing_company
  Domain                  → domain
  Phone                   → phone
  MailingStreet           → mailingstreet
  MailingCity             → mailingcity
  MailingState            → mailingstate
  MailingCountry          → mailingcountry
  MailingPostalCode       → mailingpostalcode
  HasOptedOutOfEmail      → hasoptedoutemail
"""

import contextlib
import re
from typing import Dict, List, Optional

try:
    import psycopg2
    import psycopg2.extras
    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False

import os as _os


# ── DSN builder ───────────────────────────────────────────────────────────────

def _build_oracle_dsn() -> str:
    """Build DSN from environment variables — never hardcode credentials."""
    dsn = _os.environ.get("ORACLE_PG_DSN", "").strip()
    if dsn:
        return dsn
    host     = _os.environ.get("DB_HOST", "localhost")
    port     = _os.environ.get("DB_PORT", "5432")
    dbname   = _os.environ.get("DB_NAME", "Inoapps-Data-DB")
    user     = _os.environ.get("DB_USER", "postgres")
    password = _os.environ.get("DB_PASSWORD", "")
    return f"host={host} port={port} dbname={dbname} user={user} password={password}"


# ── Module-level singleton ────────────────────────────────────────────────────

_pg_master: Optional["PGMasterStore"] = None


def init_pg_master(connection_string: str = "") -> "PGMasterStore":
    """Initialise the master store. Uses ORACLE_PG_DSN env var if no DSN given."""
    global _pg_master
    dsn = connection_string.strip() or _build_oracle_dsn()
    _pg_master = PGMasterStore(dsn)
    return _pg_master


def get_pg_master() -> Optional["PGMasterStore"]:
    global _pg_master
    if _pg_master is None:
        _pg_master = PGMasterStore(_build_oracle_dsn())
    return _pg_master


# ── Helpers ──────────────────────────────────────────────────────────────────

def _norm_company(name: str) -> str:
    """Lowercase + strip common legal suffixes for consistent company matching."""
    n = (name or "").lower().strip()
    n = re.sub(
        r"\b(incorporated|inc|llc|ltd|limited|corp|corporation|co|company|plc|private|pvt|gmbh|sa|ag|nv|bv|lp|llp)\b",
        "", n,
    )
    return re.sub(r"\s+", " ", n).strip()


# ── SELECT template (all callers use same column shape) ──────────────────────

_SELECT_COLS = """
    id::TEXT                                                              AS lead_id,
    firstname                                                             AS first_name,
    lastname                                                              AS last_name,
    title                                                                 AS job_title,
    COALESCE(NULLIF(validated_email,''), NULLIF(email,''))                AS email,
    validated_email_status                                                AS email_validation_status,
    COALESCE(NULLIF(linkedin_url__c,''), NULLIF(linkedin_url_enriched,'')) AS linkedin_url,
    domain,
    COALESCE(NULLIF(new_company,''), NULLIF(existing_company,''))         AS company,
    phone,
    mailingstreet                                                         AS street,
    mailingcity                                                           AS city,
    mailingstate                                                          AS state,
    mailingcountry                                                        AS country,
    mailingpostalcode                                                     AS postal_code
"""

_ZB_FILTER = "UPPER(TRIM(zb_valid_email)) = 'YES'"


# ── Store class ───────────────────────────────────────────────────────────────

class PGMasterStore:
    """Read-only interface to contacts_master (Salesforce CRM export)."""

    def __init__(self, connection_string: str):
        if not _HAS_PSYCOPG2:
            raise ImportError(
                "psycopg2-binary is required for the PostgreSQL master store.\n"
                "Install it with:  pip install psycopg2-binary"
            )
        self._dsn = connection_string
        # No table creation — contacts_master is a pre-existing Salesforce export

    @contextlib.contextmanager
    def _conn(self):
        conn = psycopg2.connect(self._dsn)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Writes (no-op — contacts_master is read-only) ────────────────────────

    def upsert_master_leads(self, records: List[Dict]) -> int:
        """contacts_master is a read-only Salesforce export — writes are no-ops."""
        return 0

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get_master_leads_by_ids(self, lead_ids: List[str]) -> Dict[str, Dict]:
        """Look up contacts by Salesforce ID. Only returns ZB-validated contacts."""
        if not lead_ids:
            return {}
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT {_SELECT_COLS}
                    FROM contacts_master
                    WHERE id::TEXT = ANY(%s)
                      AND {_ZB_FILTER}
                    """,
                    (lead_ids,),
                )
                rows = cur.fetchall()
        return {r["lead_id"]: dict(r) for r in rows}

    def get_master_domains_for_companies(self, company_norms: List[str]) -> Dict[str, str]:
        """
        Return the best known email domain for each normalised company name.
        Only uses contacts with a ZB-validated email.
        """
        if not company_norms:
            return {}
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT
                        LOWER(REGEXP_REPLACE(
                            COALESCE(new_company, existing_company, ''),
                            '\\s+(llc|inc|ltd|corp|limited|plc|llp|gmbh|sa|ag|nv|bv|co)\\.?$',
                            '', 'i'
                        ))                                           AS company_normalized,
                        domain,
                        COUNT(*)                                     AS cnt,
                        SUM(CASE WHEN validated_email_status = 'valid' THEN 1 ELSE 0 END) AS valid_cnt
                    FROM contacts_master
                    WHERE LOWER(REGEXP_REPLACE(
                              COALESCE(new_company, existing_company, ''),
                              '\\s+(llc|inc|ltd|corp|limited|plc|llp|gmbh|sa|ag|nv|bv|co)\\.?$',
                              '', 'i'
                          )) = ANY(%s)
                      AND domain IS NOT NULL AND domain != ''
                      AND {_ZB_FILTER}
                    GROUP BY company_normalized, domain
                    ORDER BY company_normalized, valid_cnt DESC, cnt DESC
                    """,
                    (company_norms,),
                )
                rows = cur.fetchall()
        result: Dict[str, str] = {}
        for r in rows:
            key = r["company_normalized"]
            if key not in result:
                result[key] = r["domain"]
        return result

    def get_contacts_by_company(self, company_names: List[str]) -> Dict[str, List[Dict]]:
        """
        Return ZB-validated contacts keyed by company_normalized.
        Only returns contacts where zb_valid_email = 'Yes'.
        """
        norms = [_norm_company(n) for n in company_names if n]
        if not norms:
            return {}
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT {_SELECT_COLS},
                        LOWER(REGEXP_REPLACE(
                            COALESCE(new_company, existing_company, ''),
                            '\\s+(llc|inc|ltd|corp|limited|plc|llp|gmbh|sa|ag|nv|bv|co)\\.?$',
                            '', 'i'
                        )) AS company_normalized
                    FROM contacts_master
                    WHERE LOWER(REGEXP_REPLACE(
                              COALESCE(new_company, existing_company, ''),
                              '\\s+(llc|inc|ltd|corp|limited|plc|llp|gmbh|sa|ag|nv|bv|co)\\.?$',
                              '', 'i'
                          )) = ANY(%s)
                      AND {_ZB_FILTER}
                    ORDER BY
                        CASE validated_email_status
                            WHEN 'valid'     THEN 0
                            WHEN 'catch-all' THEN 1
                            ELSE 2 END
                    """,
                    (norms,),
                )
                rows = cur.fetchall()
        result: Dict[str, List[Dict]] = {}
        for r in rows:
            key = r["company_normalized"]
            result.setdefault(key, []).append(dict(r))
        return result

    def get_validation_by_email(self, emails: List[str]) -> Dict[str, Dict]:
        """
        Return known validation status for given emails from contacts_master.
        Only returns contacts where zb_valid_email = 'Yes'.
        """
        if not emails:
            return {}
        clean = [e.lower().strip() for e in emails if e]
        if not clean:
            return {}
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        COALESCE(NULLIF(validated_email,''), NULLIF(email,''))  AS email,
                        validated_email_status                                   AS email_validation_status
                    FROM contacts_master
                    WHERE LOWER(COALESCE(NULLIF(validated_email,''), NULLIF(email,''))) = ANY(%s)
                      AND UPPER(TRIM(zb_valid_email)) = 'YES'
                    """,
                    (clean,),
                )
                rows = cur.fetchall()
        return {r["email"].lower(): dict(r) for r in rows if r.get("email")}

    def find_contacts_by_name_company(self, leads: List[Dict]) -> Dict[str, Dict]:
        """
        Look up contacts_master by (first_name, last_name, company_normalized).
        Only returns records where zb_valid_email = 'Yes'.
        Returns dict keyed by 'firstname|lastname|company_normalized'.
        """
        if not leads:
            return {}
        result: Dict[str, Dict] = {}
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                for lead in leads:
                    fn = str(lead.get("first_name") or "").lower().strip()
                    ln = str(lead.get("last_name")  or "").lower().strip()
                    cn = str(lead.get("company_normalized") or "").lower().strip()
                    if not fn or not ln or not cn:
                        continue
                    key = f"{fn}|{ln}|{cn}"
                    if key in result:
                        continue
                    cur.execute(
                        f"""
                        SELECT {_SELECT_COLS}
                        FROM contacts_master
                        WHERE LOWER(firstname) = %s
                          AND LOWER(lastname)  = %s
                          AND LOWER(REGEXP_REPLACE(
                                  COALESCE(new_company, existing_company, ''),
                                  '\\s+(llc|inc|ltd|corp|limited|plc|llp|gmbh|sa|ag|nv|bv|co)\\.?$',
                                  '', 'i'
                              )) = %s
                          AND {_ZB_FILTER}
                        ORDER BY
                            CASE validated_email_status
                                WHEN 'valid'     THEN 0
                                WHEN 'catch-all' THEN 1
                                ELSE 2 END
                        LIMIT 1
                        """,
                        (fn, ln, cn),
                    )
                    row = cur.fetchone()
                    if row:
                        result[key] = dict(row)
        return result

    def master_stats(self) -> Dict:
        """Row counts from contacts_master."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM contacts_master")
                total = cur.fetchone()[0]

                cur.execute(
                    """SELECT COUNT(*) FROM contacts_master
                       WHERE COALESCE(NULLIF(validated_email,''), NULLIF(email,'')) IS NOT NULL"""
                )
                with_email = cur.fetchone()[0]

                cur.execute(
                    """SELECT COUNT(*) FROM contacts_master
                       WHERE UPPER(TRIM(zb_valid_email)) = 'YES'"""
                )
                valid = cur.fetchone()[0]

                cur.execute(
                    """SELECT COUNT(*) FROM contacts_master
                       WHERE UPPER(TRIM(zb_valid_email)) = 'YES'
                         AND (hasoptedoutemail IS NULL OR hasoptedoutemail = FALSE)"""
                )
                ready = cur.fetchone()[0]

        return {"total": total, "with_email": with_email, "valid": valid, "ready": ready}
