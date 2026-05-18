import os
import json
from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
from src import config, database as db, pipeline, exporter, lead_scorer, contact_finder
from src.phase_classifier import PHASE_LABELS, PHASE_COLORS
from src.utils import is_valid_company_name

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY
CORS(app)


@app.before_request
def _init_db():
    app.before_request_funcs[None].remove(_init_db)
    try:
        db.init_db()
    except Exception as e:
        app.logger.error(f"DB init failed: {e}")


# ------------------------------------------------------------------ #
#  Dashboard
# ------------------------------------------------------------------ #
@app.route("/")
def index():
    db_ok = db.test_connection()
    companies = []
    scan_runs = []
    stats = {"total_companies": 0, "total_signals": 0, "phases": {}, "products": {}}

    # show_all=1 → full all-time history; default → new leads from latest run only
    show_all = request.args.get("show_all", "0") == "1"

    current_run_id = None
    if db_ok:
        try:
            current_run_id = db.get_latest_completed_run_id()
            run_filter = 0 if show_all else current_run_id
            companies = db.get_all_companies_with_signals(run_id=run_filter)
            for c in companies:
                lead_scorer.annotate(c)
            companies.sort(key=lambda c: c["priority_score"], reverse=True)
            scan_runs = db.get_recent_scan_runs(5)
            stats = _build_stats(companies)
        except Exception as e:
            app.logger.error(f"Dashboard query error: {e}")

    return render_template(
        "index.html",
        companies=companies,
        scan_runs=scan_runs,
        stats=stats,
        db_ok=db_ok,
        current_run_id=current_run_id,
        show_all=show_all,
        scan_status=pipeline.current_status(),
        phase_labels=PHASE_LABELS,
        phase_colors=PHASE_COLORS,
    )


# ------------------------------------------------------------------ #
#  Scan endpoints
# ------------------------------------------------------------------ #
@app.route("/scan/start", methods=["POST"])
def start_scan():
    status = pipeline.current_status()
    if status["status"] == "running":
        return jsonify({"error": "Scan already running.", "progress": status["progress"]}), 409

    data = request.get_json(silent=True) or {}
    sources = data.get("sources", ["indeed", "linkedin", "google_jobs", "news"])
    location = data.get("location", "")
    max_pages = int(data.get("max_pages", config.MAX_PAGES))

    pipeline.run_scan_async(location=location, max_pages=max_pages, sources=sources)
    return jsonify({"message": "Scan started.", "sources": sources})


@app.route("/scan/status")
def scan_status():
    return jsonify(pipeline.current_status())


@app.route("/scan/stop", methods=["POST"])
def stop_scan():
    pipeline.stop_scan()
    return jsonify({"message": "Stop signal sent."})


@app.route("/scan/log")
def scan_log():
    return jsonify(pipeline.get_log())


# ------------------------------------------------------------------ #
#  Data endpoints
# ------------------------------------------------------------------ #
@app.route("/api/companies")
def api_companies():
    phase = request.args.get("phase", "")
    product = request.args.get("product", "")

    companies = db.get_all_companies_with_signals()
    if phase:
        companies = [c for c in companies if phase in (c.get("phases") or [])]
    if product:
        companies = [c for c in companies if product in (c.get("products") or [])]

    return jsonify([dict(c) for c in companies])


@app.route("/api/company/<int:company_id>/signals")
def api_company_signals(company_id):
    signals = db.get_signals_for_company(company_id)
    return jsonify([dict(s) for s in signals])


@app.route("/api/company/<int:company_id>/contacts")
def api_company_contacts(company_id):
    contacts = db.get_contacts_for_company(company_id)
    return jsonify([dict(c) for c in contacts])


@app.route("/api/company/<int:company_id>/contacts/enrich", methods=["POST"])
def api_enrich_contacts(company_id):
    """Manually trigger contact enrichment (LinkedIn via Bing + Hunter.io) for a company."""
    company = db.get_company_by_id(company_id)
    if not company:
        return jsonify({"error": "Company not found"}), 404

    domain = company.get("domain") or contact_finder.infer_domain(company["name"])
    try:
        contacts = contact_finder.find_contacts(company["name"], domain)
        db.save_contacts(company_id, contacts)
        return jsonify({"contacts": contacts, "count": len(contacts)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------ #
#  Admin / data management
# ------------------------------------------------------------------ #
@app.route("/admin/purge-invalid", methods=["POST"])
def purge_invalid():
    count = db.purge_invalid_companies(is_valid_company_name)
    return jsonify({"deleted": count, "message": f"Purged {count} invalid company names."})


@app.route("/admin/reset-all", methods=["POST"])
def reset_all():
    db.reset_all_data()
    return jsonify({"message": "All data cleared. Ready for a fresh scan."})


# ------------------------------------------------------------------ #
#  Export endpoints
# ------------------------------------------------------------------ #
@app.route("/export/csv")
def export_csv():
    try:
        companies = db.get_all_companies_with_signals()
        company_dicts = _companies_to_export_format(companies)
        path = exporter.export_csv(company_dicts)
        return send_file(path, as_attachment=True, download_name=os.path.basename(path))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/export/excel")
def export_excel():
    try:
        companies = db.get_all_companies_with_signals()
        company_dicts = _companies_to_export_format(companies)
        path = exporter.export_excel(company_dicts)
        return send_file(path, as_attachment=True, download_name=os.path.basename(path))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/export/excel/all")
def export_excel_all():
    """Export every company ever found across all scan runs."""
    try:
        companies = db.get_all_companies_with_signals(run_id=0)
        company_dicts = _companies_to_export_format(companies)
        from datetime import datetime
        filename = f"oracle_intent_ALL_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        path = exporter.export_excel(company_dicts, filename=filename)
        return send_file(path, as_attachment=True, download_name=os.path.basename(path))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/export/csv/all")
def export_csv_all():
    """Export every company ever found across all scan runs as CSV."""
    try:
        companies = db.get_all_companies_with_signals(run_id=0)
        company_dicts = _companies_to_export_format(companies)
        from datetime import datetime
        filename = f"oracle_intent_ALL_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = exporter.export_csv(company_dicts, filename=filename)
        return send_file(path, as_attachment=True, download_name=os.path.basename(path))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------ #
#  Helpers
# ------------------------------------------------------------------ #
def _build_stats(companies) -> dict:
    from collections import Counter
    phase_counter: Counter = Counter()
    product_counter: Counter = Counter()
    total_signals = 0

    for c in companies:
        phases = c.get("phases") or []
        products = c.get("products") or []
        for p in phases:
            if p:
                phase_counter[p] += 1
        for p in products:
            if p:
                product_counter[p] += 1
        total_signals += int(c.get("signal_count") or 0)

    return {
        "total_companies": len(companies),
        "total_signals": total_signals,
        "phases": dict(phase_counter.most_common()),
        "products": dict(product_counter.most_common(10)),
    }


def _companies_to_export_format(db_rows) -> list[dict]:
    result = []
    for row in db_rows:
        phases = row.get("phases") or []
        products = row.get("products") or []
        sources = row.get("sources") or []

        result.append({
            "company_name": row.get("name", ""),
            "domain": row.get("domain", ""),
            "location": row.get("location", ""),
            "industry": row.get("industry", ""),
            "size": row.get("size", ""),
            "website": row.get("website", ""),
            "oracle_product": products[0] if products else "Oracle (General)",
            "all_products": [p for p in products if p],
            "phase": phases[0] if phases else "hiring",
            "all_phases": [p for p in phases if p],
            "sources": [s for s in sources if s],
            "signal_count": row.get("signal_count", 0),
            "confidence": float(row.get("max_confidence") or 0),
            "evidence": "",
            "source_url": row.get("source_url", ""),
            "signals": [],
        })
    return result


if __name__ == "__main__":
    app.run(debug=True, port=config.FLASK_PORT)
