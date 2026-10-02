# tom-transients-fyi

A [TOM Toolkit](https://tom-toolkit.readthedocs.io) data service for
[transients.fyi](https://transients.fyi): bring a view's objects into your TOM as targets, with
their light curves, non-detections included.

- **Targets from a view.** Paste the API URL from the Subscribe panel of a transients.fyi objects
  view (`https://transients.fyi/api/table?…`) or a `/tonight.json?…` URL, or fill in a few fields
  (window, source, TNS type, discovered within, brightness, a declination band, AAVSO campaigns).
  Each object becomes a SIDEREAL target named by its TNS name (else its designation or id), with
  its other names as aliases and its class, redshift, discovery night and link as extras.
- **Photometry.** Reported objects' detections and 5σ limits from transients.fyi (TNS, CBAT,
  ASAS-SN, ATLAS and AAVSO reports; magnitudes AB, Vega ones converted). ZTF and Rubin objects'
  alerts from the [Fink](https://fink-broker.org) broker: ZTF's upper limits, and Rubin's forced
  photometry on visits without a detection as 5σ limits (Rubin's times are TAI, converted to
  UTC); with the reported points of the designations they carry (an object's TNS name: TNS's,
  ATLAS's and AAVSO's points, the designation in the source name).
- **Update Reduced Data** on a target page fetches its photometry again (from its `tfyi_id`
  extra). A report that a ZTF or Rubin object takes over follows it: transients.fyi redirects
  the report's id to that object, and the target's `tfyi_id` moves there.

Requires TOM Toolkit 3 (`tom_dataservices`). Tested with tomtoolkit 3.0.1.

## Installation

    pip install tom-transients-fyi

Add the app to `INSTALLED_APPS` in your TOM's `settings.py`:

```python
INSTALLED_APPS = [
    ...
    'tom_dataservices',
    'tom_transients_fyi',
]
```

The service appears under Data Services as **transients.fyi**. No key is needed. To point it at
another copy of the site:

```python
DATA_SERVICES = {
    "transients.fyi": {"base_url": "https://transients.fyi"},
}
```

## Credits

Please credit transients.fyi and the providers of the data you use, as
[transients.fyi/data](https://transients.fyi/data) lists them: Fink (Möller et al. 2021), ZTF
(Bellm et al. 2019), the Vera C. Rubin Observatory (Ivezić et al. 2019), the TNS, CBAT, ATLAS
(Tonry et al. 2018; Smith et al. 2020; Shingles et al. 2021) and AAVSO.

## Development

With [uv](https://docs.astral.sh/uv/):

    uv sync                                                           # .venv with the locked versions
    uv run python tom_transients_fyi/tests/run_tests.py               # tests on recorded responses
    uv run python tom_transients_fyi/tests/run_tests.py --canary      # against the live services
    uv run python tom_transients_fyi/tests/check_migrations.py
    uv run ruff check . && uv run ruff format --check .

The tests run on responses recorded from transients.fyi and Fink on 2026-09-30
(`tom_transients_fyi/tests/data`). CI (`.github/workflows/ci.yml`) runs the same on Python
3.10–3.13, Linux and macOS; the canary runs daily.

## Releasing

The version comes from the git tag (hatch-vcs). Tag and push:

    git tag v0.1.0 && git push origin v0.1.0

`.github/workflows/release.yml` runs CI, builds with `uv build`, publishes to PyPI by trusted
publishing (no token) and makes a GitHub release with the files.
