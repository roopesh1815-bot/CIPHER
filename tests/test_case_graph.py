import unittest
from unittest.mock import patch

from api.routers import graph
from core.spiderweb_center import (
    build_spiderweb_center,
    case_edge_status,
    fusion_badge_rank,
    normalize_fusion_badge,
)


def node(node_id, label, entity_type="Person", roles="", **attributes):
    return {
        "id": node_id,
        "label": label,
        "entity_type": entity_type,
        "roles": roles,
        "color": "#888888",
        "size": 12,
        "sources": "FIR",
        **attributes,
    }


def case_entity(label, role, entity_type="Person", **attributes):
    return {
        "entity_label": label,
        "entity_type": entity_type,
        "role": role,
        "source": "FIR-2026-TEST",
        "confidence_tier": "observed_fact",
        **attributes,
    }


class CaseGraphTests(unittest.TestCase):
    def call_case_graph(self, entities, nodes, edges, hops=2):
        graph_data = {"nodes": nodes, "edges": edges}
        with (
            patch.object(graph, "_load_graph", return_value=graph_data),
            patch.object(graph, "fetch_all", return_value=entities),
        ):
            response = graph.get_case_graph(
                "FIR-2026-TEST", user={"username": "investigator"}, hops=hops
            )
        return response, graph_data

    def test_one_case_suspect_is_the_center(self):
        response, graph_data = self.call_case_graph(
            [case_entity("Case subject", "suspect")],
            [node("PER-1", "Case subject", roles="Associate")],
            [],
        )

        center = next(n for n in response["nodes"] if n["is_case_center"])
        self.assertEqual(center["id"], "PER-1")
        self.assertFalse(center["is_merged_center"])
        self.assertEqual(center["member_metadata"][0]["roles"], ["suspect"])
        self.assertNotIn("is_case_entity", graph_data["nodes"][0])

    def test_multiple_suspects_merge_with_member_metadata(self):
        response, _ = self.call_case_graph(
            [
                case_entity("Subject A", "Suspect", source="Case file A"),
                case_entity("Subject B", "Suspect", source="Case file B"),
            ],
            [
                node("PER-A", "Subject A", roles="Witness"),
                node("PER-B", "Subject B"),
                node("ACC-1", "Shared account", "Account"),
            ],
            [
                {"source": "PER-A", "target": "PER-B", "rel_type": "Reported together", "weight": 3},
                {"source": "PER-A", "target": "ACC-1", "rel_type": "Used account", "weight": 2.25},
            ],
        )

        center = next(n for n in response["nodes"] if n["is_case_center"])
        self.assertTrue(center["is_merged_center"])
        self.assertEqual(center["canonical_ids"], ["PER-A", "PER-B"])
        self.assertEqual(center["member_labels"], ["Subject A", "Subject B"])
        self.assertEqual(center["member_metadata"][0]["roles"], ["Suspect"])
        self.assertEqual(center["member_metadata"][0]["provenance"][0]["source"], "Case file A")
        self.assertEqual(response["internal_links"][0]["rel_type"], "Reported together")

    def test_no_suspect_uses_only_a_case_entity_as_fallback(self):
        response, _ = self.call_case_graph(
            [
                case_entity("Witness", "Witness"),
                case_entity("Associate", "Associate"),
            ],
            [
                node("PER-W", "Witness", roles="Suspect", cross_verified=False),
                node("PER-A", "Associate", roles="Suspect", cross_verified=True),
                node("PER-OUT", "Unrelated suspect", roles="Suspect", cross_verified=True),
            ],
            [],
        )

        center = next(n for n in response["nodes"] if n["is_case_center"])
        self.assertEqual(center["id"], "PER-A")
        self.assertEqual(center["center_reason"], "fallback_no_suspect")
        self.assertNotIn("PER-OUT", {n["id"] for n in response["nodes"]})

    def test_exact_label_and_type_fallback_and_canonical_id_preference(self):
        nodes = [
            node("PER-1", "Same label", "Person"),
            node("ACC-1", "Same label", "Account"),
            node("PER-2", "Different label", "Person"),
        ]
        matched, ambiguous = graph._case_entity_matches(
            [case_entity("Same label", "Associate", "person")], nodes
        )
        self.assertEqual(set(matched), {"PER-1"})
        self.assertEqual(ambiguous, 0)

        matched, ambiguous = graph._case_entity_matches(
            [case_entity("Same label", "Associate", "Person", canonical_id="ACC-1")],
            nodes,
        )
        self.assertEqual(set(matched), {"ACC-1"})
        self.assertEqual(ambiguous, 0)

    def test_ambiguous_label_fallback_is_skipped(self):
        matched, ambiguous = graph._case_entity_matches(
            [case_entity("Repeated", "Associate", "Person")],
            [node("PER-1", "Repeated"), node("PER-2", "Repeated")],
        )
        self.assertEqual(matched, {})
        self.assertEqual(ambiguous, 1)

    def test_edge_contract_preserves_value_type_status_and_non_center_links(self):
        response, _ = self.call_case_graph(
            [
                case_entity("Subject A", "Suspect"),
                case_entity("Subject B", "Suspect"),
            ],
            [
                node("PER-A", "Subject A"),
                node("PER-B", "Subject B"),
                node("ACC-1", "Account", "Account"),
                node("MOB-1", "Phone", "Mobile"),
            ],
            [
                {"source": "PER-A", "target": "ACC-1", "rel_type": "Used account", "weight": 2.75},
                {
                    "source": "PER-B",
                    "target": "ACC-1",
                    "rel_type": "AI candidate transfer",
                    "weight": 4.125,
                    "is_ai_suggested": True,
                    "provenance": "offline_link_prediction",
                },
                {
                    "source": "ACC-1",
                    "target": "MOB-1",
                    "rel_type": "References phone",
                    "weight": 1.5,
                    "status": "observed",
                },
            ],
        )

        observed = next(e for e in response["edges"] if e["rel_type"] == "Used account")
        suggested = next(e for e in response["edges"] if e["rel_type"] == "AI candidate transfer")
        non_center = next(e for e in response["edges"] if e["rel_type"] == "References phone")
        self.assertEqual(observed["value"], 2.75)
        self.assertEqual(observed["status"], "data-derived")
        self.assertEqual(suggested["value"], 4.125)
        self.assertEqual(suggested["status"], "ai_suggested")
        self.assertEqual(suggested["provenance"], "offline_link_prediction")
        self.assertEqual(non_center["value"], 1.5)
        self.assertEqual(non_center["from"], "ACC-1")
        self.assertEqual(non_center["to"], "MOB-1")
        self.assertEqual(non_center["status"], "observed")
        self.assertEqual(len(response["edges"]), 3)

    def test_observed_edge_status_is_preserved_and_predictions_are_not_inferred(self):
        self.assertEqual(case_edge_status({"status": "observed"}), "observed")
        self.assertEqual(case_edge_status({"source_file": "FIR"}), "data-derived")
        self.assertEqual(
            case_edge_status({"provenance": "AI-suggested"}),
            "ai_suggested",
        )

    def test_fusion_badges_normalize_without_changing_display_values(self):
        display_badge = "🔗 Triple-Verified"
        self.assertEqual(normalize_fusion_badge(display_badge), "triple-verified")
        self.assertEqual(fusion_badge_rank(display_badge), 3)
        self.assertEqual(fusion_badge_rank("🔗 Quad-Verified"), 4)
        self.assertEqual(fusion_badge_rank("🔗 Cross-Verified"), 2)
        self.assertEqual(fusion_badge_rank("📄 Single-Source"), 0)
        self.assertEqual(fusion_badge_rank("Unverified"), 0)
        self.assertEqual(display_badge, "🔗 Triple-Verified")

    def test_center_selection_never_uses_non_case_roles(self):
        result = build_spiderweb_center(
            [
                node("PER-CASE", "Case entity", roles="Associate", is_case_entity=True),
                node("PER-CONTEXT", "Context entity", roles="Suspect", is_case_entity=False),
            ],
            [],
        )
        self.assertEqual(result.center_node["id"], "PER-CASE")
        self.assertEqual(result.center_reason, "fallback_no_suspect")


if __name__ == "__main__":
    unittest.main()
