import unittest
from unittest.mock import patch

from api.routers import cases


class DashboardCaseLookupTests(unittest.TestCase):
    def test_entity_lookup_returns_existing_case_context_grouped_by_case(self):
        records = [
            {
                "fir_id": "FIR-2026-00002",
                "crime_type": "Fraud",
                "district": "Erode",
                "status": "Open",
                "fir_date": "2026-02-01",
                "entity_label": "Example Account",
                "entity_type": "account",
                "role": "receiver",
                "confidence_tier": "observed_fact",
                "source": "case import",
            },
            {
                "fir_id": "FIR-2026-00002",
                "crime_type": "Fraud",
                "district": "Erode",
                "status": "Open",
                "fir_date": "2026-02-01",
                "entity_label": "Example Account",
                "entity_type": "account",
                "role": "sender",
                "confidence_tier": "derived_signal",
                "source": "financial record",
            },
            {
                "fir_id": "FIR-2026-00001",
                "crime_type": "Theft",
                "district": "Salem",
                "status": "Review",
                "fir_date": "2026-01-01",
                "entity_label": "EXAMPLE ACCOUNT",
                "entity_type": "Account",
                "role": "account",
                "confidence_tier": "observed_fact",
                "source": "case import",
            },
            {
                "fir_id": "FIR-2026-00003",
                "crime_type": "Other",
                "district": "Erode",
                "status": "Open",
                "fir_date": "2026-03-01",
                "entity_label": "Example Account",
                "entity_type": "person",
                "role": "associate",
                "confidence_tier": "observed_fact",
                "source": "case import",
            },
        ]
        with (
            patch.object(
                cases,
                "_entity_identity_cache",
                {
                    "ACC-001": {
                        "entity_label": "Example Account",
                        "entity_type": "Account",
                    }
                },
            ),
            patch.object(cases, "fetch_all", return_value=records) as fetch_all,
        ):
            result = cases.get_entity_cases("ACC-001", user={"username": "investigator"})

        self.assertEqual(result["canonical_id"], "ACC-001")
        self.assertEqual(result["total"], 2)
        self.assertEqual(
            [case["fir_id"] for case in result["cases"]],
            ["FIR-2026-00002", "FIR-2026-00001"],
        )
        self.assertEqual(len(result["cases"][0]["entity_records"]), 2)
        self.assertEqual(
            result["cases"][0]["entity_records"][1]["confidence_tier"],
            "derived_signal",
        )
        self.assertEqual(
            fetch_all.call_args.args[0].count("case_entities"),
            1,
        )

    def test_unknown_canonical_id_returns_not_found(self):
        with patch.object(cases, "_entity_identity_cache", {}):
            with self.assertRaises(cases.HTTPException) as error:
                cases.get_entity_cases("MISSING", user={"username": "investigator"})

        self.assertEqual(error.exception.status_code, 404)

    def test_ambiguous_canonical_label_does_not_guess_case_associations(self):
        identities = {
            "ACC-001": {
                "entity_label": "Example Account",
                "entity_type": "Account",
            },
            "ACC-002": {
                "entity_label": "EXAMPLE ACCOUNT",
                "entity_type": "account",
            },
        }
        with (
            patch.object(cases, "_entity_identity_cache", identities),
            patch.object(cases, "fetch_all") as fetch_all,
        ):
            with self.assertRaises(cases.HTTPException) as error:
                cases.get_entity_cases("ACC-001", user={"username": "investigator"})

        self.assertEqual(error.exception.status_code, 409)
        fetch_all.assert_not_called()


if __name__ == "__main__":
    unittest.main()
