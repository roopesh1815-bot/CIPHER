"""Hidden Links API: AI-suggested connections between entities that don't share a direct edge."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.config import LINK_PREDICTIONS_CSV
...

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hidden-links", tags=["hidden_links"])

HIDDEN_LINKS_PATH = LINK_PREDICTIONS_CSV


class HiddenLink(BaseModel):
    link_id: str
    node_a: str
    node_b: str
    label_a: str
    label_b: str
    type_a: str
    type_b: str
    jaccard: float
    adamic_adar: float
    combined_score: float
    shared_neighbor_count: int
    shared_neighbors: list[str]
    note: str


def _load_hidden_links() -> list[HiddenLink]:
    if not HIDDEN_LINKS_PATH.exists():
        logger.warning("hidden links file not found at %s", HIDDEN_LINKS_PATH)
        return []
    df = pd.read_csv(HIDDEN_LINKS_PATH)
    links: list[HiddenLink] = []
    for i, row in df.iterrows():
        shared = str(row["Shared_Neighbors"]).split("|") if pd.notna(row["Shared_Neighbors"]) else []
        links.append(
            HiddenLink(
                link_id=f"HL-{row['Node_A']}-{row['Node_B']}-{i}",
                node_a=str(row["Node_A"]),
                node_b=str(row["Node_B"]),
                label_a=str(row["Label_A"]),
                label_b=str(row["Label_B"]),
                type_a=str(row["Type_A"]),
                type_b=str(row["Type_B"]),
                jaccard=float(row["Jaccard"]),
                adamic_adar=float(row["Adamic_Adar"]),
                combined_score=float(row["Combined_Score"]),
                shared_neighbor_count=int(row["Shared_Neighbor_Count"]),
                shared_neighbors=shared,
                note=str(row["Note"]),
            )
        )
    return links


@router.get("", response_model=list[HiddenLink])
def list_hidden_links(
    entity_type: Optional[str] = Query(None, description="Filter: only links where either side matches this type"),
    min_score: Optional[float] = Query(None, description="Minimum Combined_Score"),
    search: Optional[str] = Query(None, description="Case-insensitive match on either label"),
):
    links = _load_hidden_links()

    if entity_type:
        links = [l for l in links if l.type_a == entity_type or l.type_b == entity_type]
    if min_score is not None:
        links = [l for l in links if l.combined_score >= min_score]
    if search:
        needle = search.lower()
        links = [
            l for l in links
            if needle in l.label_a.lower() or needle in l.label_b.lower()
        ]

    links.sort(key=lambda l: l.combined_score, reverse=True)
    return links


@router.get("/{link_id}", response_model=HiddenLink)
def get_hidden_link(link_id: str):
    for l in _load_hidden_links():
        if l.link_id == link_id:
            return l
    raise HTTPException(status_code=404, detail="Hidden link not found")