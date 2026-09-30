# tom-transients-fyi

A [TOM Toolkit](https://tom-toolkit.readthedocs.io) data service for
[transients.fyi](https://transients.fyi): bring a view's objects into your TOM as targets, with
their light curves, non-detections included.

- **Targets from a view.** Paste the API URL from the Subscribe panel of a transients.fyi objects
  view (`https://transients.fyi/api/table?…`) or a `/tonight.json?…` URL, or fill in a few fields
  (window, source, TNS type, discovered within, brightness, a declination band, AAVSO campaigns).
  Each object becomes a SIDEREAL target named by its TNS name (else its designation or id), with
  its other names as aliases and its class, redshift, discovery night and link as extras.
- **Photometry.** Reported objects' detections and 5σ limits from transients.fyi (TNS, ATLAS and
  CBAT reports; magnitudes AB, Vega ones converted). ZTF and Rubin objects' alerts from the
  [Fink](https://fink-broker.org) broker: ZTF's upper limits, and Rubin's forced photometry on
  visits without a detection as 5σ limits (Rubin's times are TAI, converted to UTC).
- **Update Reduced Data** on a target page fetches its photometry again (from its `tfyi_id`
  extra).

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
    'transients.fyi': {'base_url': 'https://transients.fyi'},
}
```

## Credits

Please credit transients.fyi and the providers of the data you use, as
[transients.fyi/data](https://transients.fyi/data) lists them: Fink (Möller et al. 2021), ZTF
(Bellm et al. 2019), the Vera C. Rubin Observatory (Ivezić et al. 2019), the TNS, CBAT, ATLAS
(Tonry et al. 2018; Smith et al. 2020; Shingles et al. 2021) and AAVSO.

## Development

    uv venv -p 3.12 .venv && uv pip install -p .venv "tomtoolkit>=3,<4" requests factory_boy flake8
    PYTHONPATH=. .venv/bin/python tom_transients_fyi/tests/run_tests.py            # recorded responses
    PYTHONPATH=. .venv/bin/python tom_transients_fyi/tests/run_tests.py --canary   # the live services
    .venv/bin/flake8 tom_* --exclude=*/migrations/* --max-line-length=120

The tests run on responses recorded from transients.fyi and Fink on 2026-09-30
(`tom_transients_fyi/tests/data`).
