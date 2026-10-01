from django.test import TestCase, tag

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
        points = ds.query_photometry({"tfyi_id": results[0]["tfyi_id"]})
        self.assertTrue(any(p["limit"] is None for p in points))
