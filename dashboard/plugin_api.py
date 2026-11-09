"""Read-only routes for the Snitchboard tab (HSB-PRD-001 section 7.7).

Mounted by the dashboard under /api/plugins/hermes-snitchboard/. Every route
is a GET and nothing here writes to disk.

Safety rules this module keeps:

* No value supplied by a client reaches the filesystem as a path. A run
  identifier is checked against the schema pattern and then looked up among
  the names the runs directory itself returned; it is never joined onto a
  directory.
* File work happens in a worker thread, so a handler never blocks the event
  loop (NFR3).
* Every response is bounded in count and in serialised size (NFR4). Under
  plugin host isolation responses are buffered and a request that runs past
  60 seconds is cut off, so verification also carries a time budget.
* Redaction, verification and schema validation come from the snitchboard
  package; no rule is restated here.
* A malformed record is reported in the payload and never stops the others
  from being served (FR11).
"""

import asyncio
import importlib
import importlib.util
import json
import os
import stat
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

PLUGIN = "hermes-snitchboard"
ROOT = Path(__file__).resolve().parent.parent
DEMO_RUNS_DIR = ROOT / "fixtures" / "runs"

# How Hermes imports this file is not documented, so the plugin root cannot be
# assumed to be on sys.path. The engine package is loaded from its own
# directory under a private name, which also avoids clashing with any other
# module called `snitchboard`.
_ENGINE = "_hermes_snitchboard_engine"


def _load_engine():
    if _ENGINE not in sys.modules:
        package_dir = ROOT / "snitchboard"
        spec = importlib.util.spec_from_file_location(
            _ENGINE, package_dir / "__init__.py",
            submodule_search_locations=[str(package_dir)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[_ENGINE] = module
        spec.loader.exec_module(module)
    return (importlib.import_module(f"{_ENGINE}.schema"),
            importlib.import_module(f"{_ENGINE}.chain"),
            importlib.import_module(f"{_ENGINE}.redact"),
            importlib.import_module(f"{_ENGINE}.config"))


schema, chain, redact, config = _load_engine()

# ---------------------------------------------------------------- bounds

RUNS_LIMIT_DEFAULT = 50
RUNS_LIMIT_MAX = 200
SERIES_DEFAULT = 24
SERIES_MAX = 168
# Records considered at all. Hourly runs for well over a year.
MAX_RECORDS = 10_000
# A file larger than the full-record cap is malformed by definition, so it is
# never read past the cap.
READ_CAP_BYTES = schema.CAPS["full_bytes"]
SETTINGS_FILE_CAP_BYTES = 64 * 1024
PROBLEMS_SHOWN = 5
PROBLEM_CHARS = 240
VERIFY_LINKS_SHOWN = 48
VERIFY_BREAKS_SHOWN = 20
# Leaves a clear margin under the 60 second ceiling of the plugin host.
VERIFY_BUDGET_S = 40.0
RECORD_RESPONSE_MAX_BYTES = 512 * 1024
RESPONSE_MAX_BYTES = 256 * 1024

SETTING_KEYS = tuple(config.PLUGIN_DEFAULTS) + ("telemetry_destinations",)

TRIMMED_NOTICE = (
    "Trimmed records keep a shortened summary. The chain attests to their "
    "position and to the digest the full record held when it was sealed, but "
    "not to the summary now stored, so that summary is a derived analysis aid "
    "rather than evidence."
)


# ------------------------------------------------------------- settings

def _default_data_dir():
    try:
        from plugins.plugin_storage import plugin_data_dir  # documented helper
        return Path(plugin_data_dir(PLUGIN))
    except Exception:
        home = os.environ.get("HERMES_HOME") or os.path.join(
            os.path.expanduser("~"), ".hermes")
        return Path(home) / "plugin-data" / PLUGIN


def _read_raw_settings():
    """Return (raw settings, source). Never raises.

    The documented read-only helper is tried first (PRD risk R2), then a
    settings.json in the plugin data directory, then the defaults.
    """
    try:
        from hermes_cli.config import load_config_readonly
        loaded = load_config_readonly()
    except Exception:
        loaded = None
    if isinstance(loaded, dict):
        plugins = loaded.get("plugins")
        entries = plugins.get("entries") if isinstance(plugins, dict) else None
        entry = entries.get(PLUGIN) if isinstance(entries, dict) else None
        settings = entry.get("settings") if isinstance(entry, dict) else None
        return (settings if isinstance(settings, dict) else {}), "hermes"
    try:
        path = _default_data_dir() / "settings.json"
        with open(path, "rb") as handle:
            data = json.loads(handle.read(SETTINGS_FILE_CAP_BYTES + 1)
                              [:SETTINGS_FILE_CAP_BYTES])
        if isinstance(data, dict):
            return data, "file"
    except Exception:
        pass
    return {}, "defaults"


def _settings():
    raw, source = _read_raw_settings()
    picked = {k: raw[k] for k in SETTING_KEYS if k in raw}
    try:
        return config.load(picked), source, []
    except ValueError as exc:
        return config.load({}), "defaults", [
            f"saved settings were rejected, so defaults apply: {exc}"[:PROBLEM_CHARS]]


# ---------------------------------------------------------- runs on disk

def _is_run_id(value):
    # fullmatch and isascii close two gaps in a plain match: a trailing
    # newline, and digits from other scripts that \d accepts.
    return (isinstance(value, str) and value.isascii()
            and schema.RUN_ID_PATTERN.fullmatch(value) is not None)


def _dir_status(path):
    if not path.is_absolute():
        return "invalid"
    try:
        info = os.stat(path)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unreadable"
    if not stat.S_ISDIR(info.st_mode):
        return "not_a_directory"
    if not os.access(path, os.R_OK | os.X_OK):
        return "unreadable"
    return "ok"


def _list_runs(directory):
    """Return ({run_id: file path}, truncated) for regular files only.

    Paths come from the directory listing. Symbolic links are skipped so that
    nothing outside the directory can be reached through one.
    """
    found = {}
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                name = entry.name
                if not name.endswith(".json") or not _is_run_id(name[:-5]):
                    continue
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                found[name[:-5]] = entry.path
    except OSError:
        return {}, False
    truncated = len(found) > MAX_RECORDS
    if truncated:
        keep = sorted(found)[-MAX_RECORDS:]
        found = {k: found[k] for k in keep}
    return found, truncated


class _Context:
    """Settings, mode and the active set of runs for one request."""

    def __init__(self):
        self.settings, self.settings_source, self.settings_problems = _settings()
        configured = self.settings["runs_dir"]
        self.runs_dir_kind = "custom" if configured else "default"
        live_dir = Path(configured) if configured else _default_data_dir() / "runs"
        self.runs_dir_status = _dir_status(live_dir)
        live, live_truncated = ({}, False)
        if self.runs_dir_status == "ok":
            live, live_truncated = _list_runs(live_dir)
        mode = self.settings["mode"]
        if mode == "demo" or (mode == "auto" and not live):
            self.mode = "demo"
            self.runs, self.truncated = _list_runs(DEMO_RUNS_DIR)
        else:
            self.mode = "live"
            self.runs, self.truncated = live, live_truncated
        self.newest_first = sorted(self.runs, reverse=True)

    @property
    def demo(self):
        return self.mode == "demo"

    def envelope(self, **fields):
        return {"mode": self.mode, "demo": self.demo, **fields}


def _reject_constant(name):
    raise ValueError(f"{name} is not a JSON number")


def _read_record(path):
    """Return (record or None, problems). Reads at most the full-record cap."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        return None, [f"file could not be opened: {exc.strerror or exc}"]
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None, ["not a regular file"]
        if info.st_size > READ_CAP_BYTES:
            return None, [f"file is {info.st_size} bytes, above the "
                          f"{READ_CAP_BYTES} byte cap for a full record"]
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(READ_CAP_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) > READ_CAP_BYTES:
        return None, [f"file grew past the {READ_CAP_BYTES} byte cap while read"]
    try:
        record = json.loads(data.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        return None, [f"not valid JSON: {exc}"]
    return record, None


def _masked_problems(problems, record):
    """Problem texts can quote record values, so they are always masked."""
    problems = [p[:PROBLEM_CHARS] for p in problems[:PROBLEMS_SHOWN]]
    for context in (record, None):
        try:
            masked = redact.redact({"problems": problems, "context": context})
            return masked["problems"]
        except Exception:
            continue
    return [p.split(":", 1)[0] for p in problems]


def _check(record, read_problems, run_id):
    """Return the full problem list for one record, or [] when it is valid."""
    if read_problems:
        return list(read_problems)
    problems = schema.validate(record)
    if isinstance(record, dict) and record.get("run_id") != run_id:
        problems.append("record.run_id: does not match the file name")
    return problems


# Summaries are cached by file identity, so an unchanged file is not parsed
# again on every listing.
_cache_lock = threading.Lock()
_summary_cache = {}


def _summary(run_id, path):
    try:
        info = os.lstat(path)
        key = (path, info.st_mtime_ns, info.st_size, info.st_ino)
    except OSError:
        key = None
    if key is not None:
        with _cache_lock:
            hit = _summary_cache.get(path)
        if hit is not None and hit[0] == key:
            return hit[1]
    record, read_problems = _read_record(path)
    problems = _check(record, read_problems, run_id)
    if problems:
        summary = {
            "run_id": run_id, "malformed": True,
            "problem_count": len(problems),
            "problems": _masked_problems(problems, record),
        }
    else:
        counts = {s: 0 for s in schema.SEVERITIES}
        for det in record["detections"]:
            counts[det["severity"]] += 1
        totals = record["totals"]
        summary = {
            "run_id": run_id, "malformed": False,
            "started_at": record["started_at"],
            "window_start": record["window_start"],
            "window_end": record["window_end"],
            "status": record["status"],
            "trimmed": record["trimmed"],
            "run_index": record["integrity"]["run_index"],
            "severity_counts": counts,
            "_series": {
                "connections": totals["connections"],
                "ai_connections": totals["ai_connections"],
                "denied": totals["denied"],
            },
        }
    if key is not None:
        with _cache_lock:
            _summary_cache[path] = (key, summary)
            if len(_summary_cache) > 2 * MAX_RECORDS + 64:
                _summary_cache.clear()
    return summary


def _public(summary):
    return {k: v for k, v in summary.items() if not k.startswith("_")}


def _bounded(payload, limit=RESPONSE_MAX_BYTES):
    size = len(json.dumps(payload, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8"))
    if size > limit:
        raise HTTPException(status_code=500,
                            detail=f"response of {size} bytes exceeds the {limit} byte bound")
    return payload


def _parse_reveal(ctx, reveal):
    allowed = ctx.settings["allow_reveal"]
    if reveal is None:
        return allowed and not ctx.settings["redact_by_default"]
    if reveal and not allowed:
        raise HTTPException(status_code=403,
                            detail="revealing masked values is disabled in settings")
    return bool(reveal)


def _record_payload(ctx, run_id, reveal, **extra):
    record, read_problems = _read_record(ctx.runs[run_id])
    problems = _check(record, read_problems, run_id)
    if problems:
        return ctx.envelope(
            run_id=run_id, malformed=True, revealed=False,
            problem_count=len(problems),
            problems=_masked_problems(problems, record), record=None, **extra)
    shown = record if reveal else redact.redact(record)
    return ctx.envelope(run_id=run_id, malformed=False, revealed=reveal,
                        problem_count=0, problems=[], record=shown, **extra)


# ------------------------------------------------------- route bodies

def health_body():
    ctx = _Context()
    return ctx.envelope(
        plugin=PLUGIN,
        schema_version=schema.SCHEMA_VERSION,
        mode_setting=ctx.settings["mode"],
        runs_dir={"location": ctx.runs_dir_kind, "status": ctx.runs_dir_status},
        record_count=len(ctx.runs),
        records_truncated=ctx.truncated,
        settings_source=ctx.settings_source,
        settings_problems=ctx.settings_problems,
    )


def settings_body():
    ctx = _Context()
    effective = {k: ctx.settings[k] for k in SETTING_KEYS if k != "runs_dir"}
    # The directory path is withheld: under /home it names an account.
    effective["runs_dir"] = ctx.runs_dir_kind
    effective["trimmed_max_bytes"] = schema.CAPS["trimmed_bytes"]
    return ctx.envelope(settings=effective, source=ctx.settings_source,
                        problems=ctx.settings_problems)


def runs_body(limit, offset):
    if not isinstance(limit, int) or limit < 1:
        raise HTTPException(status_code=400, detail="limit must be a positive integer")
    if not isinstance(offset, int) or offset < 0:
        raise HTTPException(status_code=400, detail="offset must be zero or more")
    limit = min(limit, RUNS_LIMIT_MAX)
    ctx = _Context()
    page = ctx.newest_first[offset:offset + limit]
    items = [_public(_summary(run_id, ctx.runs[run_id])) for run_id in page]
    newest = ctx.newest_first[0] if ctx.newest_first else None
    return _bounded(ctx.envelope(
        total=len(ctx.newest_first), limit=limit, offset=offset,
        records_truncated=ctx.truncated,
        malformed_on_page=sum(1 for i in items if i["malformed"]),
        newest_run_id=newest, runs=items))


def latest_body(reveal):
    ctx = _Context()
    reveal = _parse_reveal(ctx, reveal)
    chosen, fallback, skipped = None, None, []
    for run_id in ctx.newest_first:
        summary = _summary(run_id, ctx.runs[run_id])
        if summary["malformed"]:
            if len(skipped) < PROBLEMS_SHOWN:
                skipped.append(run_id)
            continue
        if not summary["trimmed"]:
            chosen = run_id
            break
        if fallback is None:
            fallback = run_id
    chosen = chosen or fallback
    if chosen is None:
        raise HTTPException(status_code=404, detail="no readable run record was found")
    return _bounded(_record_payload(ctx, chosen, reveal, skipped_malformed=skipped),
                    RECORD_RESPONSE_MAX_BYTES)


def run_body(run_id, reveal):
    if not _is_run_id(run_id):
        raise HTTPException(status_code=400, detail="run identifier is not valid")
    ctx = _Context()
    reveal = _parse_reveal(ctx, reveal)
    if run_id not in ctx.runs:
        raise HTTPException(status_code=404, detail="no run with that identifier")
    return _bounded(_record_payload(ctx, run_id, reveal), RECORD_RESPONSE_MAX_BYTES)


def series_body(n):
    if not isinstance(n, int) or n < 1:
        raise HTTPException(status_code=400, detail="n must be a positive integer")
    n = min(n, SERIES_MAX)
    ctx = _Context()
    points = []
    for run_id in reversed(ctx.newest_first[:n]):
        summary = _summary(run_id, ctx.runs[run_id])
        point = {"run_id": run_id, "malformed": summary["malformed"]}
        if not summary["malformed"]:
            point.update(started_at=summary["started_at"], status=summary["status"],
                         **summary["_series"])
        points.append(point)
    return _bounded(ctx.envelope(n=n, points=points))


def verify_body():
    ctx = _Context()
    deadline = time.monotonic() + VERIFY_BUDGET_S
    oldest_first = sorted(ctx.runs)
    records, malformed = [], {}
    for run_id in oldest_first:
        if time.monotonic() > deadline:
            return _bounded(_verify_incomplete(
                ctx, f"verification stopped after {len(records)} of "
                     f"{len(oldest_first)} records to stay within the time budget"))
        record, read_problems = _read_record(ctx.runs[run_id])
        problems = _check(record, read_problems, run_id)
        if problems:
            malformed[run_id] = _masked_problems(problems, record)[:1]
        usable = (isinstance(record, dict) and isinstance(record.get("integrity"), dict)
                  and not any(p.startswith(("record.integrity", "record.trimmed"))
                              for p in problems))
        # A record whose integrity block cannot be trusted stands in as a bare
        # link, which the chain reports as broken rather than skipping.
        records.append(record if usable else {"run_id": run_id})
    if ctx.truncated:
        return _bounded(_verify_incomplete(
            ctx, f"more than {MAX_RECORDS} records are stored, so the chain "
                 "from its genesis cannot be checked within the bound"))
    try:
        result = chain.verify(records)
    except Exception:
        result = chain.verify([r if r.get("run_id") not in malformed else
                               {"run_id": r.get("run_id")} for r in records])
    links = result["links"]
    for link in links:
        if link["run_id"] in malformed:
            link["malformed"] = True
            link["note"] = "; ".join(filter(None, [
                link["note"], "record fails the schema: " + malformed[link["run_id"]][0]]))
    breaks = [link for link in links if link["status"] == chain.LINK_BROKEN]
    return _bounded(ctx.envelope(
        complete=True,
        intact=result["intact"],
        checked=result["checked"],
        sealed_links=result["sealed_links"],
        malformed_records=len(malformed),
        first_break=result["first_break"],
        summary=result["summary"],
        trimmed_notice=TRIMMED_NOTICE if result["sealed_links"] else "",
        links_total=len(links),
        links=links[-VERIFY_LINKS_SHOWN:],
        breaks_total=len(breaks),
        breaks=breaks[:VERIFY_BREAKS_SHOWN],
    ))


def _verify_incomplete(ctx, reason):
    return ctx.envelope(
        complete=False, intact=None, checked=0, sealed_links=0,
        malformed_records=0, first_break=None,
        summary=f"Verification did not complete: {reason}. No verdict is given.",
        trimmed_notice="", links_total=0, links=[], breaks_total=0, breaks=[])


# --------------------------------------------------------------- routes

router = APIRouter()


@router.get("/health")
async def health():
    return await asyncio.to_thread(health_body)


@router.get("/settings")
async def settings():
    return await asyncio.to_thread(settings_body)


@router.get("/runs")
async def runs(limit: int = RUNS_LIMIT_DEFAULT, offset: int = 0):
    return await asyncio.to_thread(runs_body, limit, offset)


# Declared before /runs/{run_id} so that "latest" is not read as an identifier.
@router.get("/runs/latest")
async def runs_latest(reveal: Optional[bool] = None):
    return await asyncio.to_thread(latest_body, reveal)


@router.get("/runs/{run_id}")
async def run_by_id(run_id: str, reveal: Optional[bool] = None):
    return await asyncio.to_thread(run_body, run_id, reveal)


@router.get("/series")
async def series(n: int = SERIES_DEFAULT):
    return await asyncio.to_thread(series_body, n)


@router.get("/verify")
async def verify():
    return await asyncio.to_thread(verify_body)
