"""
CIPHER API — FastAPI application entry point.
Run with:  uvicorn api.main:app --reload
"""

import sys
sys.path.insert(0, ".")

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.db import init_db
from core.case_access import require_case_access
from core.config import validate_case_id
from api.security import get_current_user
from api.routers import (
    alerts as alerts_router,
    auth as auth_router,
    case_vault as case_vault_router,
    cases as cases_router,
    communities as communities_router,
    graph as graph_router,
    hidden_links as hidden_links_router,
    influencers as influencers_router,
    risk as risk_router,
)

app = FastAPI(
    title="CIPHER — Criminal Network Analysis System",
    description="SIH-26189 | Offline crime-intelligence platform for NCRB/MHA",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory="api/static"), name="static")
templates = Jinja2Templates(directory="api/templates")

app.include_router(auth_router.router)
app.include_router(case_vault_router.router)
app.include_router(graph_router.router)
app.include_router(cases_router.router)
app.include_router(influencers_router.router)
app.include_router(risk_router.router)
app.include_router(alerts_router.router)
app.include_router(hidden_links_router.router)
app.include_router(communities_router.router)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/")
def home(request: Request):
    """
    Root route — uses the normal active-user check while preserving the login redirect.
    """
    try:
        get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request, "dashboard.html", {})


@app.get("/api/health", tags=["system"])
def health_check():
    return {"status": "ok", "service": "CIPHER API"}


@app.get("/network-graph")
def network_graph_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request, "network_graph.html", {})

@app.get("/cases")
def case_manager_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(
        request,
        "case_manager.html",
        {"is_admin": user.get("role") == "Admin"},
    )


@app.get("/key-influencers")
def key_influencers_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request, "key_influencers.html", {})


@app.get("/risk-scoring")
def risk_scoring_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request, "risk_scoring.html", {})


@app.get("/alerts")
def alerts_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request, "alerts.html", {})


@app.get("/hidden-links")
def hidden_links_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request, "hidden_links.html", {})


@app.get("/communities")
def communities_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request, "communities.html", {})


@app.get("/cases/{fir_id}/graph")
def case_graph_page(fir_id: str, request: Request, user: dict = Depends(get_current_user)):
    try:
        validate_case_id(fir_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    require_case_access(fir_id, user)
    return templates.TemplateResponse(request, "case_graph.html", {"fir_id": fir_id})