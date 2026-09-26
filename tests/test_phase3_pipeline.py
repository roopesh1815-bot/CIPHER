import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import networkx as nx
import pandas as pd

from api.routers import graph, hidden_links
from core import config
from core.artifact_cache import FileArtifactCache
from generators import gen_all
from pipeline import run_pipeline
from pipeline.graph import builder, exporter
from pipeline.intelligence import temporal_engine
from pipeline.intelligence import link_predictor


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False)


class TemporalPipelineTests(unittest.TestCase):
    def test_alert_threshold_counts_distinct_fir_ids(self):
        events = {
            "mobile-one": [
                {"FIR_ID": "FIR-1", "Date": "2026-01-01T00:00:00"},
                {"FIR_ID": "FIR-1", "Date": "2026-01-02T00:00:00"},
                {"FIR_ID": "FIR-1", "Date": "2026-01-03T00:00:00"},
            ],
            "mobile-two": [
                {"FIR_ID": "FIR-1", "Date": "2026-01-01T00:00:00"},
                {"FIR_ID": "FIR-2", "Date": "2026-01-02T00:00:00"},
                {"FIR_ID": "FIR-3", "Date": "2026-01-03T00:00:00"},
            ],
        }

        alerts = temporal_engine.detect_temporal_alerts(events)

        self.assertEqual(alerts["Entity"].tolist(), ["mobile-two"])
        self.assertEqual(alerts.iloc[0]["Case_Count_In_Window"], 3)
        self.assertEqual(alerts.iloc[0]["FIR_IDs"], "FIR-1|FIR-2|FIR-3")

    def test_temporal_stage_writes_each_requested_artifact_path(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            fir_path = folder / "fir.csv"
            timeline_path = folder / "timelines.json"
            alerts_path = folder / "alerts.csv"
            trend_path = folder / "trend.csv"
            write_csv(
                fir_path,
                ["FIR_ID", "FIR_Date", "District", "Crime_Type", "Suspect_Mobile"],
                [{
                    "FIR_ID": "FIR-1",
                    "FIR_Date": "2026-01-01",
                    "District": "Sample District",
                    "Crime_Type": "Theft",
                    "Suspect_Mobile": "9000000001",
                }],
            )

            temporal_engine.run(
                fir_path=fir_path,
                timelines_path=timeline_path,
                alerts_path=alerts_path,
                trend_path=trend_path,
            )

            self.assertTrue(timeline_path.is_file())
            self.assertTrue(alerts_path.is_file())
            self.assertTrue(trend_path.is_file())
            timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
            self.assertEqual(timeline["9000000001"][0]["FIR_ID"], "FIR-1")


class GraphFidelityTests(unittest.TestCase):
    def _build_test_graph(self, folder: Path):
        entities_path = folder / "entities.csv"
        fir_path = folder / "fir.csv"
        cdr_path = folder / "cdr.csv"
        financial_path = folder / "financial.csv"
        write_csv(
            entities_path,
            [
                "Canonical_ID", "Entity_Type", "Entity_Value", "Mobile", "Sources",
                "Source_Count", "Cross_Verified", "Fusion_Badge", "Risk_Hint",
                "Roles", "FIR_Count", "CDR_Count", "Fin_Count", "Soc_Count",
                "First_Seen", "Last_Seen",
            ],
            [
                {
                    "Canonical_ID": "PER-1", "Entity_Type": "Person", "Entity_Value": "Person A",
                    "Mobile": "111", "Sources": "FIR", "Source_Count": 1,
                    "Cross_Verified": False, "Roles": "Complainant|Victim",
                    "FIR_Count": 1, "CDR_Count": 0, "Fin_Count": 0, "Soc_Count": 0,
                },
                {
                    "Canonical_ID": "PER-2", "Entity_Type": "Person", "Entity_Value": "Person B",
                    "Mobile": "222", "Sources": "FIR", "Source_Count": 1,
                    "Cross_Verified": False, "Roles": "Victim|Suspect",
                    "FIR_Count": 1, "CDR_Count": 0, "Fin_Count": 0, "Soc_Count": 0,
                },
            ],
        )
        fir_rows = [
            {
                "FIR_ID": "FIR-1", "Incident_Date": "2026-01-01",
                "Related_FIR_ID": "FIR-2", "Complainant_Name": "Person A",
                "Complainant_Mobile": "111", "Victim_Name": "Person B",
                "Victim_Mobile": "222",
            },
            {
                "FIR_ID": "FIR-2", "Incident_Date": "2026-01-02",
                "Related_FIR_ID": "NULL", "Victim_Name": "Person A",
                "Victim_Mobile": "111", "Suspect_Name": "Person B",
                "Suspect_Mobile": "222",
            },
        ]
        write_csv(
            fir_path,
            [
                "FIR_ID", "Incident_Date", "Related_FIR_ID", "Complainant_Name",
                "Complainant_Mobile", "Victim_Name", "Victim_Mobile",
                "Suspect_Name", "Suspect_Mobile", "Associate_Name",
                "Associate_Mobile", "Witness_Name", "Witness_Mobile",
                "Incident_Location", "Vehicle_Number", "Account_Number",
            ],
            fir_rows,
        )
        write_csv(
            cdr_path,
            ["CDR_ID", "Call_DateTime", "Caller_Mobile", "Callee_Mobile", "Duration_Sec", "Call_Type"],
            [
                {
                    "CDR_ID": "CDR-1", "Call_DateTime": "2026-01-03 10:15:00",
                    "Caller_Mobile": "111", "Callee_Mobile": "222",
                    "Duration_Sec": 300, "Call_Type": "Outgoing",
                },
                {
                    "CDR_ID": "CDR-2", "Call_DateTime": "2026-01-04 11:16:00",
                    "Caller_Mobile": "222", "Callee_Mobile": "111",
                    "Duration_Sec": 600, "Call_Type": "Incoming",
                },
            ],
        )
        write_csv(
            financial_path,
            [
                "TXN_ID", "Transaction_DateTime", "Sender_Account", "Receiver_Account",
                "Amount_INR", "Suspicious_Flag", "Mobile_Ref",
            ],
            [],
        )
        return builder.build_graph(
            str(entities_path), str(fir_path), str(cdr_path), str(financial_path)
        )

    def test_related_fir_and_repeated_edge_events_survive_export_and_api(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            graph_data = self._build_test_graph(folder)
            self.assertEqual(
                graph_data.graph["related_firs"],
                [{"fir_id": "FIR-1", "related_fir_id": "FIR-2"}],
            )

            edge = graph_data["PER-1"]["PER-2"]
            self.assertEqual(edge["weight"], 9.0)
            self.assertEqual(
                edge["rel_types"],
                ["Complainant-Victim", "Victim-Suspect", "Called"],
            )
            self.assertEqual(
                [event["source_event_id"] for event in edge["events"]],
                ["FIR-1", "FIR-2", "CDR-1", "CDR-2"],
            )
            self.assertEqual(
                [event["date"] for event in edge["events"]],
                [
                    "2026-01-01", "2026-01-02",
                    "2026-01-03 10:15:00", "2026-01-04 11:16:00",
                ],
            )

            graph_path = folder / "graph.json"
            exporter.export_json(graph_data, str(graph_path))
            exported = json.loads(graph_path.read_text(encoding="utf-8"))
            exported_edge = next(
                item for item in exported["edges"]
                if {item["source"], item["target"]} == {"PER-1", "PER-2"}
            )
            self.assertEqual(exported_edge["weight"], 9.0)
            self.assertEqual(len(exported_edge["events"]), 4)
            self.assertEqual(exported["related_firs"], graph_data.graph["related_firs"])
            gexf_path = folder / "graph.gexf"
            exporter.export_gexf(graph_data, str(gexf_path))
            self.assertTrue(gexf_path.is_file())

            with (
                patch.object(graph, "GRAPH_JSON_PATH", graph_path),
                patch.object(graph, "_graph_cache", FileArtifactCache()),
            ):
                response = graph.get_graph(
                    user={"username": "investigator"},
                    community=None,
                    entity_type=None,
                    search=None,
                    limit=None,
                )
            self.assertEqual(response["related_firs"], graph_data.graph["related_firs"])
            api_edge = next(
                item for item in response["edges"]
                if {item["from"], item["to"]} == {"PER-1", "PER-2"}
            )
            self.assertEqual(api_edge["value"], 9.0)
            self.assertEqual(len(api_edge["events"]), 4)


class PipelineContractTests(unittest.TestCase):
    def test_configured_graph_and_hidden_link_artifacts_match_api_consumers(self):
        self.assertEqual(exporter.GRAPH_JSON, config.GRAPH_JSON)
        self.assertEqual(exporter.GRAPH_GEXF, config.GRAPH_GEXF)
        self.assertEqual(exporter.RELATIONSHIPS_CSV, config.RELATIONSHIPS_CSV)
        self.assertEqual(graph.GRAPH_JSON_PATH, config.GRAPH_JSON)
        self.assertEqual(link_predictor.OUT_CSV, config.LINK_PREDICTIONS_CSV)
        self.assertEqual(link_predictor.OUT_JSON, config.LINK_PREDICTIONS_JSON)
        self.assertEqual(hidden_links.HIDDEN_LINKS_PATH, config.LINK_PREDICTIONS_CSV)

    def test_hidden_link_api_reads_master_predictor_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "link_predictions.csv"
            pd.DataFrame([{
                "node_a": "PER-1",
                "node_b": "PER-2",
                "label_a": "Person A",
                "label_b": "Person B",
                "entity_type_a": "Person",
                "entity_type_b": "Person",
                "jaccard": 0.25,
                "adamic_adar": 1.5,
                "common_neighbors": 2,
                "shared_neighbors": "Person C|Account D",
                "combined_score": 0.7,
            }]).to_csv(path, index=False)
            with patch.object(hidden_links, "HIDDEN_LINKS_PATH", path):
                links = hidden_links._load_hidden_links()

        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].node_a, "PER-1")
        self.assertEqual(links[0].shared_neighbors, ["Person C", "Account D"])
        self.assertEqual(links[0].note, "AI-suggested — not a confirmed link")

    def test_pipeline_calls_existing_stages_in_order_and_uses_configured_paths(self):
        order = []
        empty_entities = pd.DataFrame({"Entity_Value": ["x"]})
        graph_data = nx.Graph()
        graph_data.add_node("PER-1")
        centrality = pd.DataFrame({"Canonical_ID": ["PER-1"]})
        anomalies = pd.DataFrame()
        communities = pd.DataFrame({"Community_ID": [0]})
        hidden = pd.DataFrame({"node_a": ["PER-1"], "node_b": ["PER-2"]})
        risk = pd.DataFrame({"Risk_Tier": ["Low"]})
        summaries = pd.DataFrame({"FIR_ID": ["FIR-1"]})
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path_values = {
                name: folder / filename
                for name, filename in {
                    "FIR_CSV": "fir.csv", "CDR_CSV": "cdr.csv",
                    "FINANCIAL_CSV": "financial.csv", "SOCIAL_CSV": "social.csv",
                    "ENTITIES_CSV": "entities.csv", "CENTRALITY_CSV": "centrality.csv",
                    "ANOMALIES_CSV": "anomalies.csv", "COMMUNITIES_CSV": "communities.csv",
                    "COMMUNITIES_JSON": "communities.json", "GRAPH_JSON": "graph.json",
                    "GRAPH_GEXF": "graph.gexf", "RELATIONSHIPS_CSV": "relationships.csv",
                    "RISK_SCORES_CSV": "risk.csv", "RISK_SCORES_JSON": "risk.json",
                    "CASE_SUMMARIES_CSV": "summaries.csv", "CASE_SUMMARIES_JSON": "summaries.json",
                }.items()
            }

            def stage(name, result):
                def call(*args, **kwargs):
                    order.append(name)
                    return result
                return call

            mocks = [
                patch.object(run_pipeline, "FIR_CSV", path_values["FIR_CSV"]),
                patch.object(run_pipeline, "CDR_CSV", path_values["CDR_CSV"]),
                patch.object(run_pipeline, "FINANCIAL_CSV", path_values["FINANCIAL_CSV"]),
                patch.object(run_pipeline, "SOCIAL_CSV", path_values["SOCIAL_CSV"]),
                patch.object(run_pipeline, "ENTITIES_CSV", path_values["ENTITIES_CSV"]),
                patch.object(run_pipeline, "CENTRALITY_CSV", path_values["CENTRALITY_CSV"]),
                patch.object(run_pipeline, "ANOMALIES_CSV", path_values["ANOMALIES_CSV"]),
                patch.object(run_pipeline, "COMMUNITIES_CSV", path_values["COMMUNITIES_CSV"]),
                patch.object(run_pipeline, "COMMUNITIES_JSON", path_values["COMMUNITIES_JSON"]),
                patch.object(run_pipeline, "GRAPH_JSON", path_values["GRAPH_JSON"]),
                patch.object(run_pipeline, "GRAPH_GEXF", path_values["GRAPH_GEXF"]),
                patch.object(run_pipeline, "RELATIONSHIPS_CSV", path_values["RELATIONSHIPS_CSV"]),
                patch.object(run_pipeline, "RISK_SCORES_CSV", path_values["RISK_SCORES_CSV"]),
                patch.object(run_pipeline, "RISK_SCORES_JSON", path_values["RISK_SCORES_JSON"]),
                patch.object(run_pipeline, "CASE_SUMMARIES_CSV", path_values["CASE_SUMMARIES_CSV"]),
                patch.object(run_pipeline, "CASE_SUMMARIES_JSON", path_values["CASE_SUMMARIES_JSON"]),
                patch.object(run_pipeline, "AUDIT_AVAILABLE", False),
                patch.object(run_pipeline, "extract_fir", stage("extract_fir", empty_entities)),
                patch.object(run_pipeline, "extract_cdr", stage("extract_cdr", empty_entities)),
                patch.object(run_pipeline, "extract_financial", stage("extract_financial", empty_entities)),
                patch.object(run_pipeline, "extract_social", stage("extract_social", empty_entities)),
                patch.object(run_pipeline, "resolve", stage("resolve", empty_entities)),
                patch.object(run_pipeline, "tag_fusion", stage("fusion", empty_entities)),
                patch.object(run_pipeline, "build_graph", stage("build_graph", graph_data)),
                patch.object(run_pipeline, "compute_centrality", stage("centrality", centrality)),
                patch.object(run_pipeline, "detect_anomalies", stage("anomalies", anomalies)),
                patch.object(run_pipeline, "detect_communities", stage("communities", ({}, communities))),
                patch.object(run_pipeline, "export_json", stage("export_json", {})),
                patch.object(run_pipeline, "export_gexf", stage("export_gexf", None)),
                patch.object(run_pipeline, "export_relationships_csv", stage("export_relationships", pd.DataFrame())),
                patch.object(run_pipeline, "predict_links", stage("predict_links", hidden)),
                patch.object(run_pipeline, "save_predictions", stage("save_predictions", None)),
                patch.object(run_pipeline, "compute_risk", stage("risk", risk)),
                patch.object(run_pipeline, "summarise_all", stage("summaries", summaries)),
                patch.object(run_pipeline, "run_temporal", stage("temporal", {})),
            ]
            entered = []
            try:
                for mock_patch in mocks:
                    entered.append(mock_patch)
                    mock_patch.start()
                result = run_pipeline.run()
            finally:
                for mock_patch in reversed(entered):
                    mock_patch.stop()

        self.assertEqual(
            order,
            [
                "extract_fir", "extract_cdr", "extract_financial", "extract_social",
                "resolve", "fusion", "build_graph", "centrality", "anomalies",
                "communities", "export_json", "export_gexf", "export_relationships",
                "predict_links", "save_predictions", "risk", "summaries", "temporal",
            ],
        )
        self.assertIn("temporal_results", result)


class GeneratorVerificationTests(unittest.TestCase):
    def test_insufficient_rows_and_missing_columns_fail_the_verification_step(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for filename, requirements in gen_all.EXPECTED_DATASETS.items():
                write_csv(folder / filename, ["wrong-column"], [{"wrong-column": "value"}])
            with patch.object(gen_all, "RAW_DIR", str(folder)):
                self.assertFalse(gen_all.run_step("verify fixture", gen_all.step_verify))


class CacheFreshnessTests(unittest.TestCase):
    def test_artifact_cache_reloads_after_change_and_does_not_keep_deleted_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            path.write_text('{"version": 1}', encoding="utf-8")
            cache = FileArtifactCache[dict]()
            loader = lambda artifact: json.loads(artifact.read_text(encoding="utf-8"))
            self.assertEqual(cache.load(path, loader), {"version": 1})

            path.write_text('{"version": 200}', encoding="utf-8")
            self.assertEqual(cache.load(path, loader), {"version": 200})

            path.unlink()
            with self.assertRaises(FileNotFoundError):
                cache.load(path, loader)
