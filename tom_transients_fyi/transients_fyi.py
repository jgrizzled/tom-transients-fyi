"""transients.fyi as a TOM Toolkit data service (tom_dataservices, TOM Toolkit 3).

A query is a view on transients.fyi: paste the API URL its Subscribe panel gives (``/api/table?…``)
or a ``/tonight.json?…`` URL, so this plugin never re-implements the site's URL keys; a few fields
cover a view without a URL. Each row becomes a SIDEREAL target named by its TNS name (else its
designation or id), with its other names as aliases and ``tfyi_id`` (``survey:object_id``) among
its extras, from which "Update Reduced Data" fetches its photometry again: reported objects' from
transients.fyi's API (detections and 5-sigma limits), ZTF's and Rubin's from the Fink broker
(ZTF's upper limits; Rubin's forced photometry on visits without a detection, as limits) with the
reported points of the designations they carry (an alert object's TNS name: TNS's, ATLAS's and
AAVSO's points) from transients.fyi. A report that a ZTF or Rubin object takes over answers a
redirect to that object: the target's ``tfyi_id`` follows it. Magnitudes are AB. Credit
transients.fyi and its sources (https://transients.fyi/data).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit

import requests
from django import forms
from django.db import IntegrityError
from tom_dataproducts.models import PhotometryReducedDatum
from tom_dataservices.dataservices import DataService, QueryServiceError
from tom_dataservices.forms import BaseQueryForm
from tom_targets.models import Target

logger = logging.getLogger(__name__)

BASE_URL = "https://transients.fyi"
FINK_URLS = {"ztf": "https://api.ztf.fink-portal.org", "lsst": "https://api.lsst.fink-portal.org"}
TIMEOUT_S = 60
# The TOM's results page caches at most 100 rows; the site's API pages 100 at a time too.
MAX_ROWS = 100
AB_ZP_NJY = 31.4
TAI_UTC_S = 37
ZTF_BANDS = {1: "g", 2: "r", 3: "i"}
ALERT_SURVEYS = ("ztf", "lsst")
REPORT_SOURCES = ("tns", "cbat", "asassn")
WINDOWS = [("1d", "last night"), ("7d", "7 nights"), ("1M", "a month"), ("3M", "3 months"),
           ("6M", "6 months"), ("1Y", "a year")]  # fmt: skip
SOURCES = [("all", "every source"), ("ztf", "ZTF"), ("lsst", "Rubin"), ("tns", "TNS"),
           ("cbat", "CBAT")]  # fmt: skip
DISC_DAYS = [("", "any time"), ("3", "3 nights"), ("7", "7 nights"), ("14", "14 nights"),
             ("30", "30 nights"), ("90", "90 nights")]  # fmt: skip
# Extras kept on a target, from a /api/table row (from /tonight.json's, what it carries).
EXTRA_KEYS = ("survey", "object_id", "class_label", "class_bucket", "tns_type", "tns_redshift",
              "discovered_night", "last_mag", "last_band", "peak_mag", "n_nights")  # fmt: skip


class TransientsFyiForm(BaseQueryForm):
    url = forms.CharField(
        required=False,
        label="View URL",
        help_text="The API URL from the Subscribe panel of a transients.fyi objects view "
        "(…/api/table?…), or a …/tonight.json?… URL. Leave empty to use the fields below.",
        widget=forms.TextInput(attrs={"placeholder": "https://transients.fyi/api/table?window=7d&tns=any"}),
    )
    window = forms.ChoiceField(choices=WINDOWS, initial="7d", required=False, label="Seen in")
    survey = forms.ChoiceField(choices=SOURCES, initial="all", required=False, label="Source")
    tns = forms.CharField(required=False, label="TNS type", help_text="'SN Ia', 'any' or 'none'")
    disc_days = forms.ChoiceField(choices=DISC_DAYS, required=False, label="Discovered within")
    mag_max = forms.FloatField(required=False, label="Brighter than (mag)")
    dec_min = forms.FloatField(required=False, min_value=-90, max_value=90, label="Dec from")
    dec_max = forms.FloatField(required=False, min_value=-90, max_value=90, label="Dec to")
    requested = forms.BooleanField(required=False, label="An AAVSO campaign asks for it")

    def simple_fields(self):
        return ["url"]

    def clean_url(self):
        url = (self.cleaned_data.get("url") or "").strip()
        if url:
            try:
                view_query(url)
            except ValueError as e:
                raise forms.ValidationError(str(e)) from e
        return url


def view_query(url: str) -> tuple[str, dict[str, str]]:
    """A pasted URL as (kind, query): "table" for …/api/table, "tonight" for …/tonight.json.
    The host is not checked, so a mirror or a local copy works too."""
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    if path.endswith("/api/table") or path == "/table":
        kind = "table"
    elif path.endswith("/tonight.json"):
        kind = "tonight"
    else:
        raise ValueError("Give a transients.fyi …/api/table?… or …/tonight.json?… URL")
    query = dict(parse_qsl(parts.query))
    return kind, query


def mag_of(flux_njy: float) -> float:
    return AB_ZP_NJY - 2.5 * math.log10(flux_njy)


def mjd_datetime(mjd: float, tai: bool = False) -> datetime:
    t = datetime(1858, 11, 17, tzinfo=timezone.utc) + timedelta(days=mjd)
    return t - timedelta(seconds=TAI_UTC_S) if tai else t


def names_of(row: dict) -> list[str]:
    """The target's name (TNS's, else the designation or id) first, then its other names."""
    partner = row.get("partner") or {}
    names = [row.get("tns_name"), row.get("cbat_name"), row.get("object_id"), partner.get("object_id")]
    out: list[str] = []
    for n in names:
        if n and n not in out:
            out.append(n)
    return out


class TransientsFyiDataService(DataService):
    name = "transients.fyi"
    verbose_name = "Transient Explorer (transients.fyi)"
    info_url = "https://transients.fyi/data"
    base_url = BASE_URL
    service_notes = (
        "Paste a view's API URL from transients.fyi's Subscribe panel, or a /tonight.json URL. "
        "Photometry: TNS, CBAT, ASAS-SN, ATLAS and AAVSO reports from transients.fyi; ZTF and Rubin "
        "alerts from Fink."
    )
    app_link = "https://transients.fyi/data"

    @classmethod
    def get_form_class(cls):
        return TransientsFyiForm

    @classmethod
    def site(cls) -> str:
        """The site's base URL: ``DATA_SERVICES['transients.fyi']['base_url']`` if set."""
        try:
            return (cls.get_configuration("base_url", BASE_URL) or BASE_URL).rstrip("/")
        except Exception:  # not configured: the public site
            return BASE_URL

    # -- queries ----------------------------------------------------------------------------

    def build_query_parameters(self, parameters, **kwargs):
        url = (parameters.get("url") or "").strip()
        if url:
            kind, query = view_query(url)
        else:
            kind = "table"
            keys = ("window", "survey", "tns", "mag_max", "dec_min", "dec_max")
            query = {k: str(parameters[k]) for k in keys if parameters.get(k) not in (None, "")}
            if parameters.get("disc_days"):
                query["disc_days"] = str(parameters["disc_days"])
            if parameters.get("requested"):
                query["requested"] = "true"
        if kind == "table":
            query["limit"] = str(min(int(query.get("limit", MAX_ROWS)), MAX_ROWS))
            query.setdefault("offset", "0")
        self.query_parameters = {"kind": kind, "query": query}
        return self.query_parameters

    def query_service(self, query_parameters, **kwargs):
        path = "/api/table" if query_parameters["kind"] == "table" else "/tonight.json"
        try:
            r = requests.get(self.site() + path, params=query_parameters["query"], timeout=TIMEOUT_S)
        except requests.RequestException as e:
            raise QueryServiceError(f"transients.fyi did not answer: {e}") from e
        if r.status_code != 200:
            raise QueryServiceError(f"transients.fyi answered {r.status_code}: {r.text[:200]}")
        self.query_results = r.json()
        return self.query_results

    def query_targets(self, query_parameters, **kwargs):
        body = self.query_service(query_parameters, **kwargs)
        rows = body.get("rows") or []
        return [self.target_result(row, query_parameters["kind"]) for row in rows[:MAX_ROWS]]

    def target_result(self, row: dict, kind: str) -> dict:
        """A row as a target result: ``tfyi_id``, its names, position and extras."""
        if kind == "tonight":  # /tonight.json's rows: degrees under other names
            row = {**row, "ra": row["ra_deg"], "dec": row["dec_deg"], "last_mag": row.get("mag"),
                   "last_band": row.get("band"), "tns_type": row.get("type")}  # fmt: skip
        names = names_of(row)
        result = {
            "tfyi_id": f"{row['survey']}:{row['object_id']}",
            "name": names[0],
            "aliases": names[1:],
            "ra": row["ra"],
            "dec": row["dec"],
            "link": f"{self.site()}/objects/{row['survey']}/{row['object_id']}",
        }
        for key in EXTRA_KEYS:
            if row.get(key) is not None:
                result[key] = row[key]
        return result

    # -- targets ----------------------------------------------------------------------------

    def create_target_from_query(self, target_result, **kwargs):
        return Target(
            name=target_result["name"],
            type="SIDEREAL",
            ra=target_result["ra"],
            dec=target_result["dec"],
            epoch=2000.0,
        )

    def create_target_extras_from_query(self, query_results, **kwargs):
        skip = {"name", "aliases", "ra", "dec", "id", "reduced_datums"}
        return {k: v for k, v in query_results.items() if k not in skip}

    def build_query_parameters_from_target(self, target, **kwargs):
        extra = target.targetextra_set.filter(key="tfyi_id").first()
        if extra is None:
            raise QueryServiceError(f"{target.name} has no tfyi_id extra: not a transients.fyi target")
        return {"tfyi_id": self.follow(extra)}

    def follow(self, extra) -> str:
        """A report's id that a ZTF or Rubin object carries now (transients.fyi answers a 307
        to it, which requests follows): the ``tfyi_id`` extra moves to that object. Unchanged
        when the site cannot say."""
        survey, object_id = extra.value.split(":", 1)
        if survey not in REPORT_SOURCES:
            return extra.value
        try:
            r = requests.get(f"{self.site()}/api/object/{survey}/{object_id}", timeout=TIMEOUT_S)
        except requests.RequestException:
            return extra.value
        if r.status_code != 200:
            return extra.value
        row = r.json()
        now = f"{row['survey']}:{row['object_id']}"
        if now != extra.value:
            logger.info("transients.fyi: %s is %s now", extra.value, now)
            extra.value = now
            extra.save()
        return now

    # -- photometry -------------------------------------------------------------------------

    def query_photometry(self, query_parameters, **kwargs):
        """The object's points, AB magnitudes: {mjd, tai, bandpass, brightness, brightness_error,
        limit, telescope, instrument, source_name, source_location}."""
        survey, object_id = query_parameters["tfyi_id"].split(":", 1)
        if survey in REPORT_SOURCES:
            return self.report_photometry(survey, object_id)
        if survey == "ztf":
            alerts = self.ztf_photometry(object_id)
        elif survey == "lsst":
            alerts = self.rubin_photometry(object_id)
        else:
            raise QueryServiceError(f"unknown source {survey}")
        return alerts + self.report_photometry(survey, object_id, missing_ok=True)

    def _get(self, url: str, params: dict, missing_ok: bool = False) -> list | dict | None:
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT_S)
        except requests.RequestException as e:
            raise QueryServiceError(f"{url} did not answer: {e}") from e
        if r.status_code == 404 and missing_ok:
            return None
        if r.status_code != 200:
            raise QueryServiceError(f"{url} answered {r.status_code}")
        return r.json()

    def report_photometry(self, survey: str, object_id: str, missing_ok: bool = False) -> list[dict]:
        """transients.fyi's reported points of an object: a report object's own, and those of
        the designations it carries (an alert object's TNS name), named in ``source_name``.
        With ``missing_ok``, none when there are none (an alert object that carries none)."""
        url = f"{self.site()}/api/object/{survey}/{object_id}/detections"
        body = self._get(url, {}, missing_ok) or {}
        out = []
        for d in body.get("detections", []):
            if d.get("mag") is None:
                continue  # a negative ATLAS difference: no magnitude
            out.append({
                "mjd": d["mjd"], "tai": False, "bandpass": d.get("filter") or d["band"],
                "brightness": d["mag"], "brightness_error": d.get("mag_err"), "limit": None,
                "telescope": d.get("telescope") or "", "instrument": d.get("instrument") or "",
                "source_name": self.source_name(d), "source_location": url,
            })  # fmt: skip
        for lim in body.get("limits", []):
            out.append({
                "mjd": lim["mjd"], "tai": False, "bandpass": lim.get("filter") or lim["band"],
                "brightness": None, "brightness_error": None, "limit": lim["lim_mag"],
                "telescope": lim.get("telescope") or "", "instrument": lim.get("instrument") or "",
                "source_name": self.source_name(lim), "source_location": url,
            })  # fmt: skip
        return out

    def source_name(self, point: dict) -> str:
        """ "transients.fyi (atlas)", and the designation a carried point is reported under:
        "transients.fyi (atlas, tns:2026abc)"."""
        who = ", ".join(x for x in (point["origin"], point.get("designation")) if x)
        return f"{self.name} ({who})"

    def ztf_photometry(self, object_id: str) -> list[dict]:
        """Fink's ZTF alerts and upper limits (d:tag valid / upperlim); a negative difference
        (isdiffpos f) is left out."""
        url = f"{FINK_URLS['ztf']}/api/v1/objects"
        cols = "i:candid,i:jd,i:fid,i:magpsf,i:sigmapsf,i:isdiffpos,i:diffmaglim,d:tag"
        rows = self._get(url, {"objectId": object_id, "withupperlim": "True", "columns": cols,
                               "output-format": "json"})  # fmt: skip
        out = []
        seen_limits = set()
        for r in rows:
            tag = r.get("d:tag") or "valid"
            mjd = float(r["i:jd"]) - 2400000.5
            band = "ZTF-" + ZTF_BANDS.get(int(r["i:fid"]), str(r["i:fid"]))
            base = {"mjd": mjd, "tai": False, "bandpass": band, "telescope": "P48",
                    "instrument": "ZTF", "source_name": "Fink (ZTF)",
                    "source_location": f"{url}?objectId={object_id}"}  # fmt: skip
            if tag == "valid":
                if str(r.get("i:isdiffpos", "t")).lower() in ("f", "0", "false"):
                    continue
                out.append({**base, "brightness": float(r["i:magpsf"]),
                            "brightness_error": float(r["i:sigmapsf"]), "limit": None})  # fmt: skip
            elif tag == "upperlim" and r.get("i:diffmaglim") is not None:
                key = (r["i:jd"], r["i:fid"])
                if key in seen_limits:
                    continue
                seen_limits.add(key)
                out.append({**base, "brightness": None, "brightness_error": None,
                            "limit": float(r["i:diffmaglim"])})  # fmt: skip
        return out

    def rubin_photometry(self, object_id: str) -> list[dict]:
        """Fink's Rubin DIASources, and its forced photometry on visits without one as 5-sigma
        limits. Times are TAI."""
        base_url = FINK_URLS["lsst"]
        params = {"diaObjectId": object_id, "output-format": "json"}
        sources = self._get(f"{base_url}/api/v1/sources", params)
        try:
            forced = self._get(f"{base_url}/api/v1/fp", params)
        except QueryServiceError:
            forced = []  # the limits are extras
        common = {"tai": True, "telescope": "Rubin", "instrument": "LSSTCam",
                  "source_name": "Fink (Rubin)"}  # fmt: skip
        out = []
        visits = set()
        for s in sources:
            visits.add(s.get("r:visit"))
            flux, err = float(s["r:psfFlux"]), float(s["r:psfFluxErr"])
            if flux <= 0:
                continue
            out.append({**common, "mjd": float(s["r:midpointMjdTai"]),
                        "bandpass": f"LSST-{s['r:band']}", "brightness": mag_of(flux),
                        "brightness_error": 2.5 / math.log(10) * err / flux, "limit": None,
                        "source_location": f"{base_url}/api/v1/sources?diaObjectId={object_id}"})  # fmt: skip
        for f in forced:
            if f.get("r:visit") in visits or f.get("r:timeWithdrawnMjdTai") is not None:
                continue
            err = float(f["r:psfFluxErr"])
            if err <= 0:
                continue
            out.append({**common, "mjd": float(f["r:midpointMjdTai"]),
                        "bandpass": f"LSST-{f['r:band']}", "brightness": None,
                        "brightness_error": None, "limit": mag_of(5 * err),
                        "source_location": f"{base_url}/api/v1/fp?diaObjectId={object_id}"})  # fmt: skip
        return out

    def create_reduced_datums_from_query(self, target, data=None, data_type="photometry", **kwargs):
        if data_type != "photometry":
            return []
        datums = []
        for p in data or []:
            try:
                datum, _ = PhotometryReducedDatum.objects.get_or_create(
                    target=target,
                    timestamp=mjd_datetime(p["mjd"], p["tai"]),
                    bandpass=p["bandpass"],
                    brightness=p["brightness"],
                    limit=p["limit"],
                    instrument=p["instrument"],
                    defaults={
                        "brightness_error": p["brightness_error"],
                        "unit": "mag",
                        "telescope": p["telescope"],
                        "source_name": p["source_name"],
                        "source_location": p["source_location"],
                    },
                )
            except IntegrityError as e:
                raise QueryServiceError(f"could not store a point of {target.name}: {e}") from e
            datums.append(datum)
        return datums
