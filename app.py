"""FastAPI backend for the LLM Visibility Dashboard."""

from __future__ import annotations

import json
import logging
import threading
import traceback
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import audit_runner
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
LOCATIONS_PATH = BASE_DIR / "locations.json"

app = FastAPI(title="LLM Visibility Dashboard")
db.init_db()

with open(LOCATIONS_PATH) as f:
    LOCATIONS = json.load(f)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class QueryItem(BaseModel):
    text: str
    intent: str | None = None


class CreateAuditRequest(BaseModel):
    name: str = Field(..., min_length=1)
    target_company: str = Field(default="Uplers", min_length=1)
    country: str | None = None
    state: str | None = None
    city: str | None = None
    llms: list[str] = Field(..., min_length=1)
    runs_per_prompt: int = Field(default=1, ge=1, le=5)
    queries: list[QueryItem] = Field(..., min_length=1)


class QuerySetRequest(BaseModel):
    name: str = Field(..., min_length=1)
    queries: list[QueryItem] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Background audit execution
# ---------------------------------------------------------------------------

def _run_audit_thread(audit_id: int) -> None:
    audit = db.get_audit(audit_id)
    if not audit:
        return

    db.update_audit_status(
        audit_id,
        status="running",
        progress_message="Initializing LLM clients...",
        mark_started=True,
    )

    try:
        progress_state = {"completed": 0, "total": audit["total_queries"]}

        def on_result(r: dict) -> None:
            db.insert_result(
                audit_id=audit_id,
                query_id=r["query_id"],
                llm=r["llm"],
                run_number=r["run_number"],
                response=r["response"],
                companies_mentioned=r["companies_mentioned"],
                target_mentioned=r["target_mentioned"],
                companies_classified=r.get("companies_classified") or {},
                target_mention_count=r.get("target_mention_count", 0),
                target_citation_count=r.get("target_citation_count", 0),
                links=r.get("links") or [],
            )

        def on_progress(completed: int, total: int, msg: str) -> None:
            progress_state["completed"] = completed
            progress_state["total"] = total
            db.update_audit_status(
                audit_id,
                progress_message=msg,
                completed_queries=completed,
            )

        audit_runner.run_audit(
            queries=audit["queries"],
            llms=audit["llms"],
            runs_per_prompt=audit["runs_per_prompt"],
            target_company=audit["target_company"],
            country=audit["location_country"],
            state=audit["location_state"],
            city=audit["location_city"],
            on_result=on_result,
            on_progress=on_progress,
        )

        results = db.get_results(audit_id)
        analysis = audit_runner.analyze(results, audit["target_company"])

        db.update_audit_status(
            audit_id,
            status="completed",
            progress_message="Audit complete",
            analysis=analysis,
            mark_completed=True,
        )
        logger.info(f"Audit #{audit_id} completed: {len(results)} results")

    except Exception as e:
        logger.error(f"Audit #{audit_id} failed: {e}\n{traceback.format_exc()}")
        db.update_audit_status(
            audit_id,
            status="failed",
            error_message=str(e),
            progress_message=f"Failed: {e}",
            mark_completed=True,
        )


# ---------------------------------------------------------------------------
# API: locations & LLMs
# ---------------------------------------------------------------------------

@app.get("/api/locations")
def get_locations():
    return LOCATIONS


@app.get("/api/llms")
def get_available_llms():
    return {"available": audit_runner.available_llms(), "all": list(audit_runner.QUERY_FUNCS.keys())}


# ---------------------------------------------------------------------------
# API: audits
# ---------------------------------------------------------------------------

@app.post("/api/audits")
def create_audit(req: CreateAuditRequest):
    valid_llms = [l for l in req.llms if l in audit_runner.QUERY_FUNCS]
    if not valid_llms:
        raise HTTPException(400, "No valid LLMs selected")

    if req.country and req.country not in LOCATIONS:
        raise HTTPException(400, f"Unknown country: {req.country}")
    if req.state and req.country:
        if req.state not in LOCATIONS.get(req.country, {}):
            raise HTTPException(400, f"Unknown state '{req.state}' for {req.country}")
    if req.city and req.country and req.state:
        if req.city not in LOCATIONS[req.country][req.state]:
            raise HTTPException(400, f"Unknown city '{req.city}' for {req.state}")

    audit_id = db.create_audit(
        name=req.name,
        target_company=req.target_company,
        country=req.country,
        state=req.state,
        city=req.city,
        llms=valid_llms,
        runs_per_prompt=req.runs_per_prompt,
        queries=[q.model_dump() for q in req.queries],
    )

    threading.Thread(target=_run_audit_thread, args=(audit_id,), daemon=True).start()
    return {"id": audit_id, "status": "pending"}


@app.get("/api/audits")
def list_audits():
    return db.list_audits()


@app.get("/api/audits/{audit_id}")
def get_audit(audit_id: int):
    audit = db.get_audit(audit_id)
    if not audit:
        raise HTTPException(404, "Audit not found")
    return audit


@app.get("/api/audits/{audit_id}/results")
def get_audit_results(audit_id: int):
    audit = db.get_audit(audit_id)
    if not audit:
        raise HTTPException(404, "Audit not found")
    results = db.get_results(audit_id)
    return {"audit": audit, "results": results}


@app.delete("/api/audits/{audit_id}")
def remove_audit(audit_id: int):
    db.delete_audit(audit_id)
    return {"deleted": audit_id}


# ---------------------------------------------------------------------------
# API: query sets
# ---------------------------------------------------------------------------

@app.get("/api/query-sets")
def get_query_sets():
    return db.list_query_sets()


@app.post("/api/query-sets")
def save_query_set(req: QuerySetRequest):
    set_id = db.upsert_query_set(req.name, [q.model_dump() for q in req.queries])
    return {"id": set_id, "name": req.name}


@app.delete("/api/query-sets/{set_id}")
def remove_query_set(set_id: int):
    db.delete_query_set(set_id)
    return {"deleted": set_id}


# ---------------------------------------------------------------------------
# Static pages
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/history")
def history_page():
    return FileResponse(STATIC_DIR / "history.html")


@app.get("/results/{audit_id}")
def results_page(audit_id: int):
    return FileResponse(STATIC_DIR / "results.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
