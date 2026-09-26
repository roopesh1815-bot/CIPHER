"""
core/spiderweb_center.py

CIPHER — spider-web case-graph: center-node selection & merge logic.

Reminder (SIH-26189 scope): this module exists to make a case's key player(s)
immediately legible to an investigator — so every merge decision here must
stay traceable back to real entities and real relationships, never a silent
collapse.

Input shape assumed (matches confirmed GET /api/graph/case/{fir_id} response):

    node = {
        "id": str, "label": str, "entity_type": str, "color": str, "size": int,
        "cross_verified": bool, "fusion_badge": str | None,
        "roles": str,        # pipe-separated, e.g. "Suspect|Associate"
        "sources": str,      # pipe-separated
        "source_count": int, "fir_count": int, "community": int,
        "first_seen": str, "last_seen": str, "is_case_entity": bool,
    }

    edge = {
        "from": str, "to": str, "value": float, "title": str,  # e.g. "Called"
    }

Public entry point: build_spiderweb_center(nodes, edges)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


FUSION_BADGE_RANK = {
    "Triple-Verified": 3,
    "Double-Verified": 2,
    "Verified": 1,
    None: 0,
    "": 0,
}

CENTER_ROLE = "Suspect"  # role that qualifies a case entity as a center candidate


def _roles(node: dict) -> list[str]:
    return [r for r in (node.get("roles") or "").split("|") if r]


def _sources(node: dict) -> list[str]:
    return [s for s in (node.get("sources") or "").split("|") if s]


def _fusion_rank(node: dict) -> int:
    return FUSION_BADGE_RANK.get(node.get("fusion_badge"), 0)


@dataclass
class CenterResult:
    center_node: dict
    edges: list[dict]                # rewired + deduped edges, ready for the frontend
    internal_links: list[dict]       # edges dropped because both ends merged into center
    center_reason: str               # "single_suspect" | "merged_suspects" | "fallback_no_suspect"
    merged_member_ids: list[str] = field(default_factory=list)


def _pick_fallback_center(case_nodes: list[dict]) -> dict:
    """No case entity is tagged 'Suspect' — pick the best-fused case entity instead."""
    def score(n: dict):
        return (
            bool(n.get("cross_verified")),
            _fusion_rank(n),
            n.get("source_count", 0),
            n.get("fir_count", 0),
        )
    return max(case_nodes, key=score)


def _build_single_center(node: dict, reason: str) -> dict:
    center = dict(node)
    center["is_merged_center"] = False
    center["center_reason"] = reason
    center["merged_members"] = [node]
    return center


def _build_merged_center(members: list[dict]) -> dict:
    ids_sorted = sorted(n["id"] for n in members)
    all_roles, all_sources = [], []
    for n in members:
        for r in _roles(n):
            if r not in all_roles:
                all_roles.append(r)
        for s in _sources(n):
            if s not in all_sources:
                all_sources.append(s)

    best_fusion = max(members, key=_fusion_rank).get("fusion_badge")
    label = " & ".join(n["label"] for n in members[:2])
    if len(members) > 2:
        label += f" +{len(members) - 2} more"

    return {
        "id": "center::" + "_".join(ids_sorted),
        "label": label,
        "entity_type": "MergedCenter",
        "color": "#c0392b",  # distinct center color; adjust to match your palette
        "size": max(n.get("size", 20) for n in members) + 10 * (len(members) - 1),
        "cross_verified": any(n.get("cross_verified") for n in members),
        "fusion_badge": best_fusion,
        "roles": "|".join(all_roles),
        "sources": "|".join(all_sources),
        "source_count": sum(n.get("source_count", 0) for n in members),
        "fir_count": max(n.get("fir_count", 0) for n in members),
        "community": members[0].get("community"),
        "first_seen": min((n.get("first_seen") for n in members if n.get("first_seen")), default=None),
        "last_seen": max((n.get("last_seen") for n in members if n.get("last_seen")), default=None),
        "is_case_entity": True,
        "is_merged_center": True,
        "center_reason": "merged_suspects",
        "merged_members": members,
    }


def _rewire_and_dedupe_edges(
    edges: list[dict], merged_ids: set[str], center_id: str
) -> tuple[list[dict], list[dict]]:
    """
    Redirect any edge touching a merged member to the center id.
    Edges where BOTH ends collapse to the center become 'internal_links'
    (dropped from the graph, kept as the reason the merge happened).
    Edges that collapse onto the same (center, other) pair after rewiring
    are combined: value summed, titles merged into a reason list.
    """
    internal_links: list[dict] = []
    combined: dict[tuple[str, str], dict] = {}

    for e in edges:
        frm = center_id if e["from"] in merged_ids else e["from"]
        to = center_id if e["to"] in merged_ids else e["to"]

        if frm == center_id and to == center_id:
            internal_links.append(e)
            continue
        if frm == to:
            continue

        key = tuple(sorted((frm, to)))
        if key in combined:
            existing = combined[key]
            existing["value"] = round(existing.get("value", 0) + e.get("value", 0), 4)
            reasons = existing.setdefault("reasons", [existing.get("title", "")])
            if e.get("title") and e["title"] not in reasons:
                reasons.append(e["title"])
            existing["title"] = ", ".join(r for r in reasons if r)
        else:
            new_edge = dict(e)
            new_edge["from"], new_edge["to"] = frm, to
            combined[key] = new_edge

    return list(combined.values()), internal_links


def build_spiderweb_center(nodes: list[dict], edges: list[dict]) -> CenterResult:
    case_nodes = [n for n in nodes if n.get("is_case_entity")]
    if not case_nodes:
        raise ValueError(
            "No is_case_entity=True nodes in this case graph — cannot choose a center."
        )

    suspects = [n for n in case_nodes if CENTER_ROLE in _roles(n)]

    if len(suspects) == 0:
        fallback = _pick_fallback_center(case_nodes)
        center = _build_single_center(fallback, reason="fallback_no_suspect")
        merged_ids = {fallback["id"]}

    elif len(suspects) == 1:
        center = _build_single_center(suspects[0], reason="single_suspect")
        merged_ids = {suspects[0]["id"]}

    else:
        center = _build_merged_center(suspects)
        merged_ids = {n["id"] for n in suspects}

    rewired_edges, internal_links = _rewire_and_dedupe_edges(
        edges, merged_ids, center["id"]
    )

    return CenterResult(
        center_node=center,
        edges=rewired_edges,
        internal_links=internal_links,
        center_reason=center["center_reason"],
        merged_member_ids=sorted(merged_ids),
    )