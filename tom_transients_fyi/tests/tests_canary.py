from django.test import TestCase, tag
from tom_targets.models import Target

from tom_transients_fyi.transients_fyi import TransientsFyiDataService


@tag("canary")
class TestLiveServices(TestCase):
    """Against the live transients.fyi and Fink: catches a change in their APIs.
    NOTE: To run these tests in your venv: python ./tom_transients_fyi/tests/run_tests.py --canary"""

    def test_a_view_and_its_photometry(self):
        ds = TransientsFyiDataService()
        url = "https://transients.fyi/api/table?window=1M&tns=any&survey=ztf&limit=2"
        query = ds.build_query_parameters({"url": url})
        results = ds.query_targets(query)
        self.assertTrue(results)
        self.assertTrue(all(r["tfyi_id"].startswith("ztf:") for r in results))
        # Not necessarily a detection: an object long faded below its reference (SN 2018evc on
        # 2026-10-01) has only negative differences, which are left out, and upper limits.
        points = ds.query_photometry({"tfyi_id": results[0]["tfyi_id"]})
        self.assertTrue(points)
        for p in points:
            self.assertTrue((p["brightness"] is None) != (p["limit"] is None), p)
            if p["source_name"] != "Fink (ZTF)":  # a carried TNS name's reported points
                self.assertTrue(p["source_name"].startswith("transients.fyi ("), p)
                continue
            self.assertEqual((p["telescope"], p["instrument"]), ("P48", "ZTF"))
            self.assertTrue(p["bandpass"].startswith("ZTF-"), p)

    def test_a_tns_name_resolves_to_the_object_that_carries_it(self):
        """A ZTF object's TNS name, as a tns: id, answers a redirect to it (build v29)."""
        ds = TransientsFyiDataService()
        url = "https://transients.fyi/api/table?window=1M&tns=named&survey=ztf&limit=1"
        (result,) = ds.query_targets(ds.build_query_parameters({"url": url}))
        core = result["name"].split(" ", 1)[1]
        target = Target.objects.create(name=result["name"], type="SIDEREAL", ra=1, dec=2)
        target.targetextra_set.create(key="tfyi_id", value=f"tns:{core}")
        query = ds.build_query_parameters_from_target(target)
        self.assertTrue(query["tfyi_id"].startswith("ztf:"), query)
        points = ds.query_photometry(query)
        self.assertTrue(any(p["source_name"].startswith("transients.fyi (tns") for p in points))
