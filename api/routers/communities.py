"""Communities API: detected gangs/clusters from Louvain community detection."""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.security import get_current_user
from core.config import COMMUNITIES_CSV

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/communities", tags=["communities"])

MEMBER_PREVIEW_LIMIT = 25  # full lists can run 400+ members — show a preview, not a dump


class CommunitySummary(BaseModel):
    community_id: int
    label: str
    size: int
    internal_edges: int
    dominant_type: str
    has_suspect: bool
    cross_verified: int
    member_preview: list[str]
    member_id_preview: list[str]


class CommunityDetail(CommunitySummary):
    members: list[str]
    member_ids: list[str]


def _load_communities_df() -> pd.DataFrame:
    if not COMMUNITIES_CSV.exists():
        logger.warning("communities file not found at %s", COMMUNITIES_CSV)
        return pd.DataFrame()
    return pd.read_csv(COMMUNITIES_CSV)


def _split(value) -> list[str]:
    return str(value).split("|") if pd.notna(value) else []


def _row_to_summary(row) -> CommunitySummary:
    members = _split(row["Members"])
    member_ids = _split(row["Member_IDs"])
    return CommunitySummary(
        community_id=int(row["Community_ID"]),
        label=str(row["Community_Label"]),
        size=int(row["Size"]),
        internal_edges=int(row["Internal_Edges"]),
        dominant_type=str(row["Dominant_Type"]),
        has_suspect=bool(row["Has_Suspect"]),
        cross_verified=int(row["Cross_Verified"]),
        member_preview=members[:MEMBER_PREVIEW_LIMIT],
        member_id_preview=member_ids[:MEMBER_PREVIEW_LIMIT],
    )


@router.get("", response_model=list[CommunitySummary])
def list_communities(
    user: dict = Depends(get_current_user),
    dominant_type: Optional[str] = Query(None, description="Filter: e.g. Account, Person, Vehicle"),
    has_suspect: Optional[bool] = Query(None, description="Filter: only communities containing a suspect"),
    min_size: Optional[int] = Query(None, description="Minimum member count"),
):
    df = _load_communities_df()
    if df.empty:
        return []

    if dominant_type:
        df = df[df["Dominant_Type"] == dominant_type]
    if has_suspect is not None:
        df = df[df["Has_Suspect"] == has_suspect]
    if min_size is not None:
        df = df[df["Size"] >= min_size]

    df = df.sort_values("Size", ascending=False)
    return [_row_to_summary(row) for _, row in df.iterrows()]


@router.get("/{community_id}", response_model=CommunityDetail)
def get_community(community_id: int, user: dict = Depends(get_current_user)):
    df = _load_communities_df()
    match = df[df["Community_ID"] == community_id]
    if match.empty:
        raise HTTPException(status_code=404, detail="Community not found")
    row = match.iloc[0]
    summary = _row_to_summary(row)
    return CommunityDetail(
        **summary.model_dump(),
        members=_split(row["Members"]),
        member_ids=_split(row["Member_IDs"]),
    )