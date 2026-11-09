"""Hash chain: sealing, trimming and verification (HSB-PRD-001 section 7.3).

A full record's content_sha256 covers the record with its integrity block
removed, and each record's prev_sha256 names the link digest of the one
before it.

Trimming changes content, so a trimmed record keeps its original digest in
sealed_sha256 and that sealed digest remains the link the next record points
at. Its content_sha256 is recomputed over the trimmed content, which detects
an edit made after trimming. It cannot detect an edit made together with a
recomputed content_sha256, because nothing later in the chain covers the
trimmed form. Verification therefore reports every trimmed record as a sealed
link, never as verified.
"""

import copy

from . import schema
from .canonical import canonical_bytes, sha256_of

LINK_VERIFIED = "verified"
LINK_SEALED = "sealed"
LINK_BROKEN = "broken"

SEALED_NOTE = (
    "Trimmed record: the original content was discarded at trimming and "
    "cannot be re-derived, so this link rests on its sealed digest."
)


class TrimError(ValueError):
    """A record cannot be trimmed within the cap without losing destinations."""


def content_digest(record):
    return sha256_of({k: v for k, v in record.items() if k != "integrity"})


def link_digest(record):
    """The digest the next record's prev_sha256 must name."""
    block = record["integrity"]
    if record.get("trimmed"):
        return block["sealed_sha256"]
    return block["content_sha256"]


def seal(record, previous=None):
    """Return a copy of a full record with its integrity block filled in."""
    if record.get("trimmed"):
        raise ValueError("only a full record can be sealed")
    sealed = copy.deepcopy(record)
    sealed.pop("integrity", None)
    if previous is None:
        prev_sha, index = schema.GENESIS_SHA256, 0
    else:
        prev_sha = link_digest(previous)
        index = previous["integrity"]["run_index"] + 1
    sealed["integrity"] = {
        "content_sha256": content_digest(sealed),
        "prev_sha256": prev_sha,
        "run_index": index,
    }
    return sealed


def _summarise_detection(det, limit):
    def cut(text):
        # Cut at a word boundary: a name cut mid-way reads as a different name.
        if len(text) <= limit:
            return text
        head = text[: limit - 3]
        space = head.rfind(" ")
        return (head[:space] if space > 0 else head).rstrip() + "..."
    return {
        "title": cut(det["title"]),
        "severity": det["severity"],
        "confidence": det["confidence"],
        "attack": dict(det["attack"]),
        "detail": cut(det["detail"]),
        "evidence": [cut(det["evidence"][0])] if det["evidence"] else ["(none retained)"],
        "recommendation": cut(det["recommendation"]),
    }


def trim(record, text_limit=160):
    """Return the trimmed form of a sealed full record.

    Summary detections keep every mandatory field, shortened, so the strict
    schema still holds. If the trimmed record exceeds its cap, the lowest
    severity detections are dropped and the count is stated in the note.
    Destinations are never dropped, because novelty depends on them; if they
    alone exceed the cap a TrimError is raised instead.
    """
    if record.get("trimmed"):
        raise ValueError("record is already trimmed")
    original = record["integrity"]
    if content_digest(record) != original["content_sha256"]:
        raise ValueError(f"{record.get('run_id')}: content does not match its "
                         "digest, so it must not be sealed into a trimmed form")
    detections = sorted(
        (_summarise_detection(d, text_limit) for d in record["detections"]),
        key=lambda d: schema.SEVERITY_RANK[d["severity"]],
    )
    base = {name: copy.deepcopy(record[name]) for name in schema.COMMON_FIELDS
            if name != "integrity"}
    base["trimmed"] = True
    base["destinations"] = list(record["destinations"])
    note = record["note"]
    dropped = 0
    while True:
        candidate = dict(base)
        candidate["detections"] = detections[: len(detections) - dropped]
        candidate["note"] = note if not dropped else (
            f"{note} {dropped} lower-severity detection(s) were omitted at "
            "trimming to respect the size cap.").strip()
        integrity = {
            "content_sha256": content_digest(candidate),
            "sealed_sha256": original["content_sha256"],
            "prev_sha256": original["prev_sha256"],
            "run_index": original["run_index"],
        }
        candidate["integrity"] = integrity
        if len(canonical_bytes(candidate)) <= schema.CAPS["trimmed_bytes"]:
            return candidate
        if dropped >= len(detections):
            raise TrimError(
                f"{record.get('run_id')}: {len(base['destinations'])} destinations "
                f"do not fit in {schema.CAPS['trimmed_bytes']} bytes")
        dropped += 1


def verify(records):
    """Verify records given in chain order, oldest first.

    Returns a dict with `intact`, `first_break` (None or the first failing
    link), `links` (one entry per record) and a plain-language `summary`.
    Every record is examined even after a break, so all faults are listed.
    """
    links = []
    first_break = None
    sealed = 0
    previous = None
    for position, record in enumerate(records):
        run_id = record.get("run_id") if isinstance(record, dict) else None
        problems = []
        status = LINK_VERIFIED
        note = ""
        block = record.get("integrity") if isinstance(record, dict) else None
        trimmed = isinstance(record, dict) and record.get("trimmed") is True
        required = ("content_sha256", "prev_sha256", "run_index") + (
            ("sealed_sha256",) if trimmed else ())
        if not isinstance(block, dict) or any(k not in block for k in required):
            problems.append("integrity block missing or incomplete")
        else:
            if content_digest(record) != block["content_sha256"]:
                problems.append(
                    "trimmed content was altered after trimming" if trimmed
                    else "content does not match content_sha256")
            if trimmed:
                status = LINK_SEALED
                note = SEALED_NOTE
            if previous is None:
                if block["prev_sha256"] != schema.GENESIS_SHA256 or block["run_index"] != 0:
                    problems.append("first record is not the genesis link, so an "
                                    "earlier run may have been removed")
            elif previous is not False:
                if block["prev_sha256"] != link_digest(previous):
                    problems.append("prev_sha256 does not name the preceding run, "
                                    "so a run was removed, inserted or reordered")
                if block["run_index"] != previous["integrity"]["run_index"] + 1:
                    problems.append(
                        f"run_index {block['run_index']} does not follow "
                        f"{previous['integrity']['run_index']}")
        if problems:
            status = LINK_BROKEN
            note = "; ".join(problems)
        elif trimmed:
            sealed += 1
        link = {"position": position, "run_id": run_id, "status": status, "note": note}
        links.append(link)
        if status == LINK_BROKEN and first_break is None:
            first_break = link
        # A record without a usable block cannot anchor the next link.
        previous = record if isinstance(block, dict) and all(
            k in block for k in required) else False

    intact = first_break is None and bool(records)
    if not records:
        summary = "No runs to verify."
    elif intact:
        summary = f"Chain intact across {len(records)} run(s)."
        if sealed:
            summary += (f" {sealed} of them are trimmed: their links rest on sealed "
                        "digests and their original content cannot be re-derived.")
    else:
        summary = (f"Chain broken at position {first_break['position']} "
                   f"({first_break['run_id']}): {first_break['note']}.")
    return {
        "intact": intact,
        "checked": len(records),
        "sealed_links": sealed,
        "first_break": first_break,
        "links": links,
        "summary": summary,
    }
