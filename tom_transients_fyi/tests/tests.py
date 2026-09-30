"""The data service on responses recorded from transients.fyi and Fink on 2026-09-30 (tests/data).

To run them in your venv: python ./tom_transients_fyi/tests/run_tests.py
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from tom_dataproducts.models import PhotometryReducedDatum
from tom_dataservices.dataservices import QueryServiceError, get_data_service_classes
from tom_targets.models import Target

from tom_transients_fyi.transients_fyi import (
    TransientsFyiDataService,
    TransientsFyiForm,
    mjd_datetime,
    view_query,
)

DATA = Path(__file__).parent / "data"
GET = "tom_transients_fyi.transients_fyi.requests.get"


def load(name):
    return json.loads((DATA / name).read_text())


class Reply:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status
        self.text = json.dumps(body)

    def json(self):
        return self.body


def fake_get(routes):
    """requests.get answering from ``routes`` (a URL suffix -> body), and recording the calls."""
    calls = []

    def get(url, params=None, timeout=None):
        calls.append((url, dict(params or {})))
        for suffix, body in routes.items():
            if url.endswith(suffix):
                return Reply(body)
        return Reply({"detail": "not found"}, 404)

    get.calls = calls
    return get


class TestQueries(TestCase):
    def setUp(self):
        self.ds = TransientsFyiDataService()

    def test_registered_with_the_toolkit(self):
        self.assertIs(get_data_service_classes()["transients.fyi"], TransientsFyiDataService)

    def test_view_urls(self):
        self.assertEqual(
            view_query("https://transients.fyi/api/table?window=7d&tns=any&limit=100&offset=0"),
            ("table", {"window": "7d", "tns": "any", "limit": "100", "offset": "0"}),
        )
        self.assertEqual(view_query("https://transients.fyi/tonight.json?site=palomar&lim=17")[0], "tonight")
        with self.assertRaises(ValueError):
            view_query("https://transients.fyi/objects?window=7d")
        form = TransientsFyiForm(data={"url": "https://transients.fyi/sky", "data_service": "transients.fyi"})
        self.assertFalse(form.is_valid())
        self.assertIn("url", form.errors)

    def test_query_parameters_from_a_url_or_the_fields(self):
        q = self.ds.build_query_parameters({"url": "https://transients.fyi/api/table?window=1M&limit=500"})
        self.assertEqual(q, {"kind": "table", "query": {"window": "1M", "limit": "100", "offset": "0"}})
        q = self.ds.build_query_parameters(
            {"url": "", "window": "7d", "survey": "all", "tns": "none", "disc_days": "7", "dec_max": -30.0,
             "requested": True}
        )  # fmt: skip
        self.assertEqual(
            q["query"],
            {"window": "7d", "survey": "all", "tns": "none", "dec_max": "-30.0", "disc_days": "7",
             "requested": "true", "limit": "100", "offset": "0"},
        )  # fmt: skip

    def test_targets_from_a_table_view(self):
        get = fake_get({"/api/table": load("table.json")})
        with patch(GET, get):
            q = self.ds.build_query_parameters({"url": "https://transients.fyi/api/table?window=7d&tns=any"})
            results = self.ds.query_targets(q)
        self.assertEqual(get.calls[0][0], "https://transients.fyi/api/table")
        self.assertEqual(len(results), 3)
        first = results[0]
        self.assertEqual(first["tfyi_id"], "ztf:ZTF26abrxzal")
        self.assertEqual(first["name"], "SN 2026aakk")  # the TNS name first
        self.assertIn("ZTF26abrxzal", first["aliases"])
        self.assertEqual(first["link"], "https://transients.fyi/objects/ztf/ZTF26abrxzal")
        self.assertIn("tns_type", first)

    def test_targets_from_tonight(self):
        with patch(GET, fake_get({"/tonight.json": load("tonight.json")})):
            q = self.ds.build_query_parameters({"url": "https://transients.fyi/tonight.json?site=palomar&lim=17"})
            results = self.ds.query_targets(q)
        row = load("tonight.json")["rows"][0]
        self.assertEqual(len(results), 3)
        self.assertEqual((results[0]["ra"], results[0]["dec"]), (row["ra_deg"], row["dec_deg"]))
        self.assertEqual(results[0]["tfyi_id"], f"{row['survey']}:{row['object_id']}")

    def test_an_error_from_the_site_is_a_query_error(self):
        with patch(GET, fake_get({})):
            with self.assertRaises(QueryServiceError):
                self.ds.query_targets({"kind": "table", "query": {}})


class TestTargetsAndPhotometry(TestCase):
    def setUp(self):
        self.ds = TransientsFyiDataService()
        with patch(GET, fake_get({"/api/table": load("table.json")})):
            self.results = self.ds.query_targets({"kind": "table", "query": {}})

    def test_to_target_saves_names_and_extras(self):
        target = self.ds.to_target(self.results[0])
        self.assertEqual(target.name, "SN 2026aakk")
        self.assertEqual(target.type, "SIDEREAL")
        self.assertIn("ZTF26abrxzal", target.names)
        extras = {e.key: e.value for e in target.targetextra_set.all()}
        self.assertEqual(extras["tfyi_id"], "ztf:ZTF26abrxzal")
        self.assertEqual(self.ds.build_query_parameters_from_target(target), {"tfyi_id": "ztf:ZTF26abrxzal"})
        other = Target.objects.create(name="not ours", type="SIDEREAL", ra=1, dec=2)
        with self.assertRaises(QueryServiceError):
            self.ds.build_query_parameters_from_target(other)

    def test_report_photometry_with_limits(self):
        body = load("detections.json")
        # The object's limits were still being fetched on 2026-09-30: one in the API's shape.
        body["limits"] = [{"mjd": 61211.1, "band": "o", "lim_mag": 19.4, "flux": None, "flux_err": None,
                           "origin": "tns", "remark": "[Last non detection]", "filter": "orange-ATLAS",
                           "mag_system": "AB", "instrument": "ATLAS-01", "telescope": "ATLAS-HKO"}]  # fmt: skip
        with patch(GET, fake_get({"/detections": body})):
            points = self.ds.query_photometry({"tfyi_id": "tns:2026pub"})
        dets = [p for p in points if p["limit"] is None]
        lims = [p for p in points if p["limit"] is not None]
        self.assertEqual(len(dets), 4)
        self.assertEqual((dets[0]["bandpass"], dets[0]["brightness"]), ("V-crts-CRTS", 18.72))  # AB, converted
        self.assertEqual((lims[0]["limit"], lims[0]["telescope"]), (19.4, "ATLAS-HKO"))
        self.assertEqual(dets[1]["source_name"], "transients.fyi (tns)")

    def test_ztf_photometry_from_fink(self):
        rows = load("ztf_objects.json")
        get = fake_get({"/api/v1/objects": rows})
        with patch(GET, get):
            points = self.ds.query_photometry({"tfyi_id": "ztf:ZTF26abxkuhv"})
        self.assertEqual(get.calls[0][1]["withupperlim"], "True")
        valid = [r for r in rows if r["d:tag"] == "valid" and r["i:isdiffpos"] == "t"]
        limits = {(r["i:jd"], r["i:fid"]) for r in rows if r["d:tag"] == "upperlim"}
        self.assertEqual(sum(p["limit"] is None for p in points), len(valid))
        self.assertEqual(sum(p["limit"] is not None for p in points), len(limits))
        self.assertTrue(all(p["bandpass"].startswith("ZTF-") for p in points))

    def test_rubin_photometry_with_forced_limits(self):
        sources, forced = load("lsst_sources.json"), load("lsst_fp.json")
        with patch(GET, fake_get({"/api/v1/sources": sources, "/api/v1/fp": forced})):
            points = self.ds.query_photometry({"tfyi_id": "lsst:313853517444939794"})
        visits = {s["r:visit"] for s in sources}
        quiet = [f for f in forced if f["r:visit"] not in visits]
        self.assertEqual(sum(p["limit"] is not None for p in points), len(quiet))
        self.assertEqual(sum(p["limit"] is None for p in points), sum(s["r:psfFlux"] > 0 for s in sources))
        self.assertTrue(all(p["tai"] for p in points))
        # Rubin's times are TAI: 37 s ahead of UTC.
        self.assertEqual(mjd_datetime(61000.0, tai=True), datetime(2025, 11, 20, 23, 59, 23, tzinfo=timezone.utc))

    def test_reduced_datums_are_stored_once(self):
        target = self.ds.to_target(self.results[0])
        with patch(GET, fake_get({"/api/v1/objects": load("ztf_objects.json")})):
            data = self.ds.query_reduced_data(target)
        first = self.ds.to_reduced_datums(target, data)
        self.assertGreater(len(first), 0)
        self.ds.to_reduced_datums(target, data)  # "Update Reduced Data" again: nothing new
        self.assertEqual(PhotometryReducedDatum.objects.filter(target=target).count(), len(first))
        limit = PhotometryReducedDatum.objects.filter(target=target, limit__isnull=False).first()
        self.assertEqual((limit.unit, limit.telescope), ("mag", "P48"))
