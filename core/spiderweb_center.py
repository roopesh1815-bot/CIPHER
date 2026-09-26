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
import re

CENTER_ROLE = "Suspect"  # role that qualifies a case entity as a center candidate


def normalize_fusion_badge(value: object) -> str:
    """Normalize user-facing fusion labels without changing their display value."""
    words = re.sub(r"[^a-z]+", " ", str(value or "").casefold()).split()
    for label in ("quad-verified", "triple-verified", "double-verified",
                  "cross-verified", "single-source", "verified"):
        expected = label.replace("-", " ").split()
        if any(words[index:index + len(expected)] == expected for index in range(len(words))):
            return label
    return ""


def fusion_badge_rank(value: object) -> int:
    return {
        "quad-verified": 4,
        "triple-verified": 3,
        "double-verified": 2,
        "cross-verified": 2,
        "verified": 1,
    }.get(normalize_fusion_badge(value), 0)


def case_edge_status(edge: dict) -> str:
    """Return an explicit, neutral status for an existing graph edge."""
    provenance = str(
        edge.get("provenance") or edge.get("source_file") or edge.get("source") or ""
    ).casefold().replace("-", "_").replace(" ", "_")
    status = str(edge.get("status") or "").casefold().replace("-", "_")
    suggested = (
        edge.get("is_predicted") is True
        or edge.get("is_ai_suggested") is True
        or status in {"ai_suggested", "predicted", "suggested"}
        or "ai_suggested" in provenance
        or "predicted" in provenance
    )
    if suggested:
        return "ai_suggested"
    if status == "observed":
        return "observed"
    return "data-derived"


def _roles(node: dict) -> list[str]:
    roles = node.get("case_roles", node.get("roles")) or ""
    if isinstance(roles, str):
        return [r.strip() for r in roles.split("|") if r.strip()]
    return [str(role).strip() for role in roles if str(role).strip()]


def _sources(node: dict) -> list[str]:
    return [s for s in (node.get("sources") or "").split("|") if s]


def _fusion_rank(node: dict) -> int:
    return fusion_badge_rank(node.get("fusion_badge"))


@dataclass
class CenterResult:
    center_node: dict
    edges: list[dict]                # rewired edges, ready for the frontend
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
            str(n.get("id", "")),
        )
    return max(case_nodes, key=score)


def _build_single_center(node: dict, reason: str) -> dict:
    center = dict(node)
    center["is_merged_center"] = False
    center["is_case_center"] = True
    center["center_reason"] = reason
    center["canonical_ids"] = [node["id"]]
    center["member_labels"] = [node.get("label", node["id"])]
    center["merged_members"] = [dict(node)]
    center["member_metadata"] = [{
        "canonical_id": node["id"],
        "label": node.get("label", node["id"]),
        "roles": _roles(node),
        "provenance": node.get("case_provenance", []),
        "sources": _sources(node),
    }]
    return center


def _build_merged_center(members: list[dict]) -> dict:
    members = sorted(members, key=lambda n: n["id"])
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

    member_metadata = [{
        "canonical_id": n["id"],
        "label": n.get("label", n["id"]),
        "roles": _roles(n),
        "provenance": n.get("case_provenance", []),
        "sources": _sources(n),
    } for n in members]

    return {
        "id": "center::" + "_".join(ids_sorted),
        "label": label,
        "entity_type": "MergedCenter",
        "color": "#0f766e",
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
        "is_case_center": True,
        "center_reason": "merged_suspects",
        "canonical_ids": ids_sorted,
        "member_labels": [n.get("label", n["id"]) for n in members],
        "merged_members": [dict(n) for n in members],
        "member_metadata": member_metadata,
    }


def _rewire_edges(
    edges: list[dict], merged_ids: set[str], center_id: str
) -> tuple[list[dict], list[dict]]:
    """
    Redirect edges touching a merged member to the center id without
    aggregating distinct evidence, relationship types, or edge values.
    """
    internal_links: list[dict] = []
    rewired: list[dict] = []

    for e in edges:
        frm = center_id if e["from"] in merged_ids else e["from"]
        to = center_id if e["to"] in merged_ids else e["to"]

        if frm == center_id and to == center_id:
            internal_links.append(e)
            continue
        if frm == to:
            continue

        new_edge = dict(e)
        new_edge["from"], new_edge["to"] = frm, to
        rewired.append(new_edge)

    return rewired, internal_links


def build_spiderweb_center(nodes: list[dict], edges: list[dict]) -> CenterResult:
    case_nodes = [n for n in nodes if n.get("is_case_entity")]
    if not case_nodes:
        raise ValueError(
            "No is_case_entity=True nodes in this case graph — cannot choose a center."
        )

    suspects = [
        n for n in case_nodes
        if any(role.casefold() == CENTER_ROLE.casefold() for role in _roles(n))
    ]

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

    rewired_edges, internal_links = _rewire_edges(
        edges, merged_ids, center["id"]
    )

    return CenterResult(
        center_node=center,
        edges=rewired_edges,
        internal_links=internal_links,
        center_reason=center["center_reason"],
        merged_member_ids=sorted(merged_ids),
    )