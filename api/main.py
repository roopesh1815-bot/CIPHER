"""
CIPHER API — FastAPI application entry point.
Run with:  uvicorn api.main:app --reload
"""

import sys
sys.path.insert(0, ".")

from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse

from core.db import init_db
from api.security import get_current_user
from api.routers import auth as auth_router

app = FastAPI(
    title="CIPHER — Criminal Network Analysis System",
    description="SIH-26189 | Offline crime-intelligence platform for NCRB/MHA",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory="api/static"), name="static")
templates = Jinja2Templates(directory="api/templates")

app.include_router(auth_router.router)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/")
def home(request: Request):
    """
    Root route — checks the session cookie directly (rather than depending
    on get_current_user, which would throw a 401 instead of redirecting).
    """
    from api.security import decode_access_token, COOKIE_NAME
    token = request.cookies.get(COOKIE_NAME)
    if not token or decode_access_token(token) is None:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request, "dashboard.html", {})


@app.get("/api/health", tags=["system"])
def health_check():
    return {"status": "ok", "service": "CIPHER API"}

from api.routers import auth as auth_router, graph as graph_router
# ...
app.include_router(auth_router.router)
app.include_router(graph_router.router)

@app.get("/network-graph")
def network_graph_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request, "network_graph.html", {})

from api.routers import auth as auth_router, graph as graph_router, cases as cases_router
# ...
app.include_router(cases_router.router)

@app.get("/cases")
def case_manager_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request, "case_manager.html", {})


from api.routers import influencers
app.include_router(influencers.router)

@app.get("/key-influencers")
def key_influencers_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request, "key_influencers.html", {})

from api.routers import auth as auth_router, graph as graph_router, cases as cases_router, influencers as influencers_router, risk as risk_router
# ...
app.include_router(risk_router.router)

@app.get("/risk-scoring")
def risk_scoring_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request, "risk_scoring.html", {})


from api.routers import alerts as alerts_router
app.include_router(alerts_router.router)

from api.routers import alerts as alerts_router
app.include_router(alerts_router.router)

@app.get("/alerts")
def alerts_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request, "alerts.html", {})

from api.routers import hidden_links as hidden_links_router
app.include_router(hidden_links_router.router)

@app.get("/hidden-links")
def hidden_links_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request, "hidden_links.html", {})


from api.routers import communities as communities_router
app.include_router(communities_router.router)

@app.get("/communities")
def communities_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request, "communities.html", {})

@app.get("/cases/{fir_id}/graph")
def case_graph_page(fir_id: str, request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request, "case_graph.html", {"fir_id": fir_id})