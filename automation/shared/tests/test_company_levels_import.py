import csv
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
MAINTENANCE_DIR = REPO_ROOT / "automation" / "maintenance"
if str(MAINTENANCE_DIR) not in sys.path:
    sys.path.insert(0, str(MAINTENANCE_DIR))

from import_company_levels import (  # noqa: E402
    ImportValidationError,
    import_company_levels,
    load_records,
)


def row(**changes):
    result = {
        "company": "Acme",
        "level": "Engineer II",
        "aliases": ["SWE II"],
        "title_patterns": ["Software Engineer II"],
        "normalized": "mid",
        "google_min": 4.0,
        "google_max": 4.6,
        "required_yoe_min": 2,
        "required_yoe_max": 5,
        "base_min": 120000,
        "base_max": 160000,
        "stock_min": 20000,
        "stock_max": 50000,
        "bonus_min": 10000,
        "bonus_max": 20000,
        "total_min": 160000,
        "total_max": 230000,
        "currency": "USD",
        "period": "year",
        "geography": "US",
        "location_patterns": ["United States"],
        "provider": "Acme compensation survey",
        "url": "https://data.example/acme",
        "retrieved_at": "2026-07-01",
        "confidence": "medium",
        "sample_size": 40,
        "method": "licensed survey",
        "statistic": "p25-p75",
        "access_method": "licensed_export",
        "license": "Internal licensed export",
    }
    result.update(changes)
    return result


def find_level(cache):
    return cache["companies"][0]["levels"][0]


class CompanyLevelsImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write_yaml(self, name, data):
        path = self.root / name
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    def test_loads_yaml_json_and_csv(self):
        yaml_path = self.write_yaml("rows.yaml", {"records": [row()]})
        json_path = self.root / "rows.json"
        json_path.write_text(json.dumps([row()]), encoding="utf-8")
        csv_path = self.root / "rows.csv"
        csv_row = row(
            aliases='["SWE II", "E2"]',
            title_patterns="Software Engineer II|Backend Engineer II",
            location_patterns='["United States"]',
        )
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(csv_row))
            writer.writeheader()
            writer.writerow(csv_row)

        for path in (yaml_path, json_path, csv_path):
            with self.subTest(suffix=path.suffix):
                loaded = load_records(path)
                self.assertEqual(len(loaded), 1)
                self.assertEqual(loaded[0]["company"], "Acme")
                self.assertEqual(loaded[0]["google_max"], 4.6)
        self.assertEqual(
            load_records(csv_path)[0]["title_patterns"],
            ["Software Engineer II", "Backend Engineer II"],
        )

    def test_levels_fyi_policy_rejects_unlicensed_or_disallowed_access(self):
        for changes in (
            {
                "provider": "Levels.fyi",
                "url": "https://www.levels.fyi/companies/acme",
                "access_method": "browser_copy",
            },
            {
                "provider": "Levels.fyi",
                "url": "https://www.levels.fyi/companies/acme",
                "access_method": "licensed_api",
                "license": "",
            },
            {"access_method": "web_scrape"},
            {"access_method": "crawler_export"},
        ):
            with self.subTest(changes=changes):
                path = self.write_yaml("rejected.yaml", [row(**changes)])
                with self.assertRaises(ImportValidationError):
                    load_records(path)

    def test_levels_fyi_policy_accepts_explicit_licensed_export(self):
        path = self.write_yaml(
            "accepted.yaml",
            [row(
                provider="Levels.fyi",
                url="https://www.levels.fyi/companies/acme",
                access_method="licensed_export",
                license="Enterprise export under contract",
            )],
        )
        loaded = load_records(path)
        self.assertEqual(loaded[0]["access_method"], "licensed_export")

    def test_keeps_compensation_components_distinct_and_never_derives_total(self):
        input_path = self.write_yaml("components.yaml", [row(total_min=None, total_max=None)])
        result = import_company_levels(
            input_path, self.root / "cache.yaml", write=False)
        compensation = find_level(result)["compensation"]
        self.assertEqual(
            set(compensation),
            {"salary_range", "stock_range", "bonus_range"},
        )
        self.assertNotIn("total_compensation_range", compensation)
        salary_band = compensation["salary_range"]["bands"][0]
        stock_band = compensation["stock_range"]["bands"][0]
        bonus_band = compensation["bonus_range"]["bands"][0]
        self.assertEqual((salary_band["min"], salary_band["max"]), (120000, 160000))
        self.assertEqual((stock_band["min"], stock_band["max"]), (20000, 50000))
        self.assertEqual((bonus_band["min"], bonus_band["max"]), (10000, 20000))
        self.assertEqual(
            salary_band["provenance"]["component_coverage"],
            ["level", "google_equivalent", "required_yoe", "base", "stock", "bonus"],
        )

    def test_preserves_geographies_as_separate_bands(self):
        input_path = self.write_yaml(
            "geographies.yaml",
            [
                row(
                    geography="Seattle, WA",
                    location_patterns=["Seattle"],
                    base_min=140000,
                    base_max=180000,
                ),
                row(
                    geography="New York, NY",
                    location_patterns=["New York"],
                    base_min=160000,
                    base_max=210000,
                ),
            ],
        )
        salary = find_level(import_company_levels(
            input_path, self.root / "cache.yaml"))["compensation"]["salary_range"]
        self.assertIsNone(salary["min"])
        self.assertIsNone(salary["max"])
        self.assertEqual(
            {
                (band["geography"], band["min"], band["max"])
                for band in salary["bands"]
            },
            {
                ("Seattle, WA", 140000, 180000),
                ("New York, NY", 160000, 210000),
            },
        )

    def test_manual_override_tier_and_freshness_resolution(self):
        existing = {
            "schema_version": 2,
            "unrelated": {"keep": True},
            "companies": [{
                "name": "Acme",
                "custom_company_key": "preserved",
                "levels": [{
                    "name": "Engineer II",
                    "custom_level_key": "preserved",
                    "google_equivalent": {
                        "min": 3.5,
                        "max": 4.0,
                        "provenance": {
                            "tier": "market_benchmark",
                            "provider": "manual",
                            "retrieved_at": "2020-01-01",
                            "manual_override": True,
                        },
                    },
                    "required_yoe": {
                        "min": 1,
                        "max": 3,
                        "provenance": {
                            "tier": "employer_official",
                            "provider": "old official",
                            "retrieved_at": "2025-01-01",
                        },
                    },
                    "compensation": {
                        "salary_range": {
                            "min": 100000,
                            "max": 130000,
                            "currency": "USD",
                            "period": "year",
                            "provenance": {
                                "tier": "market_benchmark",
                                "provider": "new benchmark",
                                "retrieved_at": "2026-07-15",
                            },
                        },
                        "bonus_range": {
                            "min": 5000,
                            "max": 10000,
                            "currency": "USD",
                            "period": "year",
                            "provenance": {
                                "tier": "market_benchmark",
                                "provider": "old benchmark",
                                "retrieved_at": "2024-01-01",
                            },
                        },
                    },
                }],
            }],
        }
        destination = self.write_yaml("cache.yaml", existing)
        input_path = self.write_yaml(
            "refresh.yaml",
            [row(
                geography="",
                location_patterns=[],
                provider="employer_official",
                access_method="user_supplied",
                license="Employer-provided document",
                retrieved_at="2026-06-01",
                google_min=4.2,
                google_max=4.8,
                required_yoe_min=3,
                required_yoe_max=6,
                base_min=150000,
                base_max=190000,
                bonus_min=15000,
                bonus_max=25000,
            )],
        )
        level = find_level(import_company_levels(input_path, destination))
        self.assertEqual(
            (level["google_equivalent"]["min"], level["google_equivalent"]["max"]),
            (3.5, 4.0),
        )
        self.assertEqual(
            (level["required_yoe"]["min"], level["required_yoe"]["max"]),
            (3, 6),
        )
        self.assertEqual(
            level["compensation"]["salary_range"]["min"], 150000)
        self.assertEqual(
            level["compensation"]["bonus_range"]["min"], 15000)
        self.assertEqual(level["custom_level_key"], "preserved")

        older_benchmark = self.write_yaml(
            "older.yaml",
            [row(
                geography="",
                location_patterns=[],
                provider="market survey",
                retrieved_at="2023-01-01",
                base_min=90000,
                base_max=110000,
            )],
        )
        level = find_level(import_company_levels(older_benchmark, destination))
        self.assertEqual(
            level["compensation"]["salary_range"]["min"], 100000)

    def test_rejects_malformed_nonfinite_negative_and_unordered_ranges(self):
        invalid_rows = (
            row(google_min="not-a-number"),
            row(google_min=math.nan),
            row(required_yoe_min=-1),
            row(base_min=200000, base_max=100000),
            row(currency="US"),
            row(period="fortnight"),
            row(base_min=150000, base_max=200000, period="hour"),
        )
        for index, invalid in enumerate(invalid_rows):
            with self.subTest(index=index):
                path = self.write_yaml(f"invalid-{index}.yaml", [invalid])
                with self.assertRaises(ImportValidationError):
                    load_records(path)

    def test_dry_run_does_not_create_or_modify_destination(self):
        input_path = self.write_yaml("rows.yaml", [row()])
        missing = self.root / "missing-cache.yaml"
        result = import_company_levels(input_path, missing)
        self.assertFalse(missing.exists())
        self.assertEqual(result["schema_version"], 2)

        existing = self.write_yaml(
            "existing-cache.yaml",
            {"schema_version": 2, "sentinel": "unchanged", "companies": []},
        )
        before = existing.read_bytes()
        import_company_levels(input_path, existing, write=False)
        self.assertEqual(existing.read_bytes(), before)

    def test_repeated_write_is_idempotent_and_preserves_unrelated_data(self):
        input_path = self.write_yaml("rows.yaml", [row()])
        destination = self.write_yaml(
            "cache.yaml",
            {
                "schema_version": 1,
                "compensation_max_age_days": 999,
                "custom_top_level": {"preserve": "me"},
                "companies": [{
                    "name": "Other Corp",
                    "unrelated": True,
                    "levels": [],
                }],
            },
        )
        first = import_company_levels(input_path, destination, write=True)
        first_bytes = destination.read_bytes()
        second = import_company_levels(input_path, destination, write=True)
        second_bytes = destination.read_bytes()

        self.assertEqual(first, second)
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(second["schema_version"], 2)
        self.assertEqual(second["compensation_max_age_days"], 999)
        self.assertEqual(second["custom_top_level"], {"preserve": "me"})
        self.assertEqual(
            {company["name"] for company in second["companies"]},
            {"Other Corp", "Acme"},
        )

    def test_valid_bound_is_not_replaced_by_imported_null(self):
        destination = self.write_yaml(
            "cache.yaml",
            {
                "schema_version": 2,
                "companies": [{
                    "name": "Acme",
                    "levels": [{
                        "name": "Engineer II",
                        "google_equivalent": {
                            "min": 4.0,
                            "max": 4.5,
                            "provenance": {
                                "tier": "market_benchmark",
                                "provider": "old survey",
                                "retrieved_at": "2025-01-01",
                            },
                        },
                    }],
                }],
            },
        )
        input_path = self.write_yaml(
            "partial.yaml",
            [row(
                google_min=4.2,
                google_max=None,
                retrieved_at="2026-01-01",
            )],
        )
        google = find_level(import_company_levels(
            input_path, destination))["google_equivalent"]
        self.assertEqual((google["min"], google["max"]), (4.0, 4.5))
        self.assertEqual(google["provenance"]["provider"], "old survey")


if __name__ == "__main__":
    unittest.main()
