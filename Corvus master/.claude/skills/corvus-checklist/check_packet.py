#!/usr/bin/env python3
"""
check_packet.py  --  Corvus intake assistant, the checking half.

The MODEL reads a scanned packet and writes an "extraction" JSON describing
what is on the pages (see schema in SKILL.md). This file is the CODE half:
given that extraction, it applies EVERY rule on Meena's checklist and returns
a verdict. No judgement calls, no model here -- plain, testable code.

    from check_packet import check_packet
    verdict = check_packet(extracted)   # extracted = dict from the model

Returns:
    {
      "treatment_type": "cataract" | ... | None,
      "status":        "complete" | "incomplete" | "needs_review",
      "missing_items": ["doc.biometry", ...],   # Meena's item IDs, [] if complete
      "evidence":      {"doc.biometry": "why / which page", ...},
      "reason":        "..."    # filled only when status == needs_review
    }

Decision order (deliberately conservative -- a FALSE COMPLETE is the worst
mistake the brief calls out):
    1. definite missing/invalid items  -> incomplete
    2. else any required item uncertain -> needs_review  (never silently "complete")
    3. else                              -> complete

Run directly to check one extraction file:
    python check_packet.py samples/D01_extracted.json
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKLIST_PATH = HERE / "checklist.json"

VALID_TREATMENTS = {"cataract", "tka", "appendectomy", "delivery", "ptca"}


def load_checklist(path: Path = CHECKLIST_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _filled(value) -> bool:
    """A field counts as filled if it is a non-empty, non-null value."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _parse_date(value):
    """Accept an ISO 'YYYY-MM-DD' string (the format the extractor must emit)."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _norm_side(value):
    """Normalise a laterality string to 'left' / 'right' / None."""
    if not value or not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in ("l", "left", "os", "od_left"):
        return "left"
    if v in ("r", "right", "od", "os_right"):
        # NB: OD = right eye, OS = left eye. The extractor should already send
        # 'left'/'right'; this is only a loose fallback.
        return "right"
    if "left" in v:
        return "left"
    if "right" in v:
        return "right"
    return None


def _docs_of(extracted: dict, dtype: str) -> list:
    # tolerate malformed entries (a model may emit a bare string now and then)
    docs = extracted.get("documents", []) or []
    return [d for d in docs if isinstance(d, dict) and d.get("type") == dtype]


def _standalone_docs_of(extracted: dict, dtype: str) -> list:
    """Documents of a type that are real standalone reports, not a mention
    inside another document (mentions_only == True)."""
    return [d for d in _docs_of(extracted, dtype) if not d.get("mentions_only", False)]


def _page_of(doc: dict):
    p = doc.get("page")
    return f"p.{p}" if p else "page unknown"


def _uncertain_items(extracted: dict) -> dict:
    """Map item_id -> reason, for anything the model flagged it could not read.

    Tolerates both shapes the model produces:
      [{"item": "form.diagnosis", "reason": "illegible"}]   (expected)
      ["form.diagnosis", "doc.ecg"]                          (bare strings)
    """
    out = {}
    for u in extracted.get("uncertain", []) or []:
        if isinstance(u, dict):
            item = u.get("item")
            if item:
                out[item] = u.get("reason", "flagged uncertain by the reader")
        elif isinstance(u, str) and u.strip():
            out[u.strip()] = "flagged uncertain by the reader"
    return out


# --------------------------------------------------------------------------- #
# the required-item list for a packet
# --------------------------------------------------------------------------- #
def required_items(treatment: str, extracted: dict, checklist: dict) -> list:
    items = list(checklist["common_items"])
    items += list(checklist["treatment_items"].get(treatment, []))

    # note.lscs_indication applies only to caesarean deliveries
    if treatment == "delivery":
        mode = (extracted.get("form", {}) or {}).get("delivery_mode")
        if (mode or "").strip().lower() != "caesarean":
            items = [i for i in items if i != "note.lscs_indication"]
    return items


# --------------------------------------------------------------------------- #
# the core check
# --------------------------------------------------------------------------- #
def check_packet(extracted: dict, checklist: dict | None = None) -> dict:
    if checklist is None:
        checklist = load_checklist()

    rules = checklist["rules"]
    form = extracted.get("form", {})
    if not isinstance(form, dict):
        form = {}
    treatment = (extracted.get("treatment_type") or "").strip().lower() or None

    evidence: dict[str, str] = {}

    # ---- treatment type must be known to pick the right rules ----
    if treatment not in VALID_TREATMENTS:
        return {
            "treatment_type": None,
            "status": "needs_review",
            "missing_items": [],
            "evidence": {},
            "reason": "Treatment type could not be determined from the packet, "
                      "so the right checklist cannot be chosen.",
        }

    uncertain = _uncertain_items(extracted)
    required = required_items(treatment, extracted, checklist)

    missing: list[str] = []      # definite failures
    unsure: dict[str, str] = {}  # required items the reader could not judge

    def fail(item: str, why: str):
        if item not in missing:
            missing.append(item)
        evidence[item] = why

    def mark_unsure(item: str, why: str):
        unsure[item] = why
        evidence.setdefault(item, why)

    # Pre-compute shared values
    admission = _parse_date(form.get("admission_date"))
    admission_type = (form.get("admission_type") or "").strip().lower()
    operative_side = _norm_side(form.get("laterality"))
    laterality_kind = rules["laterality_by_treatment"].get(treatment)  # 'eye'/'knee'/None

    # A packet may carry more than one cost estimate (e.g. an original and a
    # signed REVISED one). Consider them all: the item is satisfied if ANY
    # estimate qualifies, and a required line item may appear in any of them.
    cost_estimates = _docs_of(extracted, "cost_estimate")
    line_items = [li for est in cost_estimates for li in (est.get("line_items") or [])
                  if isinstance(li, dict)]

    # --------------------------------------------------------------------- #
    # evaluate each required item
    # --------------------------------------------------------------------- #
    for item in required:
        # the reader already told us it could not read this -> unsure
        if item in uncertain:
            mark_unsure(item, uncertain[item])
            continue

        # ---------------- form fields ----------------
        if item == "form.patient_name":
            if not _filled(form.get("patient_name")):
                fail(item, "Patient name is blank on the form (p.1)")

        elif item == "form.hospital_id":
            if not _filled(form.get("hospital_id")):
                fail(item, "Hospital network ID is blank on the form (p.1)")

        elif item == "form.doctor_name":
            if not _filled(form.get("doctor_name")):
                fail(item, "Treating doctor's name is blank on the form (p.1)")

        elif item == "form.doctor_reg_no":
            if not _filled(form.get("doctor_reg_no")):
                fail(item, "Doctor's registration number is blank on the form (p.1)")

        elif item == "form.diagnosis":
            if not _filled(form.get("diagnosis")):
                fail(item, "Provisional diagnosis is blank on the form (p.1)")

        elif item == "form.procedure":
            if not _filled(form.get("procedure")):
                fail(item, "Proposed treatment is blank on the form (p.1)")

        elif item == "form.length_of_stay":
            if not _filled(form.get("length_of_stay")):
                fail(item, "Expected length of stay is blank on the form (p.1)")

        elif item == "form.estimated_cost":
            if not _filled(form.get("estimated_cost")):
                fail(item, "Estimated total cost is blank on the form (p.1)")

        elif item == "form.admission_date":
            if not _filled(form.get("admission_date")):
                fail(item, "Date of admission is blank on the form (p.1)")
            elif admission is None:
                fail(item, f"Date of admission '{form.get('admission_date')}' is not a valid date (p.1)")

        elif item == "form.doctor_signature":
            if not form.get("doctor_signature_present", False):
                fail(item, "Treating doctor's signature is missing on the form (p.1)")

        elif item == "form.patient_signature":
            if not form.get("patient_signature_present", False):
                # an attendant may sign for an emergency admission; the reader
                # records any such signature as patient_signature_present=True,
                # so a False here is a genuine gap.
                fail(item, "Patient's / attendant's signature is missing on the form (p.1)")

        elif item == "form.member_id":
            mid = form.get("member_id")
            if not _filled(mid):
                fail(item, "Corvus member ID is blank on the form (p.1)")
            else:
                # must match the ID card if one is present (names may confirm)
                cards = _docs_of(extracted, "id_card")
                if cards:
                    card = cards[0]
                    card_mid = (card.get("member_id") or "").strip()
                    form_mid = str(mid).strip()
                    name_form = (form.get("patient_name") or "").strip().lower()
                    name_card = (card.get("name") or "").strip().lower()
                    names_match = bool(name_form) and name_form == name_card
                    if card_mid and card_mid != form_mid and not names_match:
                        fail(item, f"Member ID on form ({form_mid}) does not match the "
                                   f"ID card ({card_mid}, {_page_of(card)}) and names differ")

        elif item == "form.icd10":
            code = (form.get("icd10") or "").strip()
            if not _filled(code):
                fail(item, "ICD-10 code is blank on the form (p.1)")
            else:
                prefixes = rules["icd10_prefixes"].get(treatment, [])
                code_u = code.upper().replace(" ", "")
                if prefixes and not any(code_u.startswith(p) for p in prefixes):
                    fail(item, f"ICD-10 '{code}' is not consistent with {treatment} "
                               f"(expected one of {', '.join(prefixes)}) (p.1)")

        # ---------------- documents common to all ----------------
        elif item == "doc.id_card":
            cards = _docs_of(extracted, "id_card")
            if not cards:
                fail(item, "No member e-card or photo ID attached")
            else:
                card = cards[0]
                name_form = (form.get("patient_name") or "").strip().lower()
                name_card = (card.get("name") or "").strip().lower()
                if name_form and name_card and name_form != name_card:
                    # ID in a different person's name
                    cm = (card.get("member_id") or "").strip()
                    fm = str(form.get("member_id") or "").strip()
                    if not (cm and fm and cm == fm):
                        fail(item, f"ID card is in the name '{card.get('name')}' "
                                   f"({_page_of(card)}), not the patient '{form.get('patient_name')}'")

        elif item == "doc.clinical_note":
            notes = _standalone_docs_of(extracted, "clinical_note")
            if not notes:
                fail(item, "No consultation / admission note attached")
            else:
                note = notes[0]
                if admission_type == "emergency":
                    pass  # an admission note is enough; no date window
                else:
                    ndate = _parse_date(note.get("date"))
                    if ndate is None:
                        mark_unsure(item, f"Consultation note has no readable date ({_page_of(note)}); "
                                          "cannot confirm it is within 30 days of admission")
                    elif admission is not None:
                        gap = (admission - ndate).days
                        limit = rules["clinical_note_max_days_before_admission"]
                        if gap < 0:
                            fail(item, f"Consultation note dated {note.get('date')} is AFTER admission "
                                       f"{form.get('admission_date')} ({_page_of(note)})")
                        elif gap > limit:
                            fail(item, f"Consultation note dated {note.get('date')} is {gap} days before "
                                       f"admission, older than the {limit}-day limit ({_page_of(note)})")

        elif item == "doc.cost_estimate":
            if not cost_estimates:
                fail(item, "No cost estimate attached")
            else:
                # pass if ANY attached estimate qualifies; else report the
                # least-bad one's problems (prefer a signed estimate's issue).
                tol = rules["cost_tolerance_pct"]
                fcost = form.get("estimated_cost")
                best_problems, best_est = None, None
                for est in cost_estimates:
                    problems = []
                    if not est.get("on_letterhead", False):
                        problems.append("not on hospital letterhead")
                    if not est.get("signed", False):
                        problems.append("not signed by the hospital")
                    etotal = est.get("total")
                    if _filled(etotal) and _filled(fcost):
                        try:
                            etotal_f, fcost_f = float(etotal), float(fcost)
                            if fcost_f > 0:
                                diff_pct = abs(etotal_f - fcost_f) / fcost_f * 100.0
                                if diff_pct > tol:
                                    problems.append(
                                        f"total Rs {int(etotal_f):,} differs from form "
                                        f"Rs {int(fcost_f):,} by {diff_pct:.0f}% (> {tol}%)")
                        except (TypeError, ValueError):
                            pass
                    if not problems:
                        best_problems, best_est = [], est
                        break  # a fully valid estimate -> item satisfied
                    # keep the most promising candidate for the error message
                    if best_problems is None or est.get("signed") and not best_est.get("signed"):
                        best_problems, best_est = problems, est
                if best_problems:
                    fail(item, f"Cost estimate ({_page_of(best_est)}): " + "; ".join(best_problems))

        # ---------------- cataract ----------------
        elif item == "doc.biometry":
            docs = _standalone_docs_of(extracted, "biometry")
            if not docs:
                fail(item, "No biometry report attached")
            else:
                _check_side(item, docs[0], operative_side, laterality_kind, fail, mark_unsure)

        # ---------------- tka ----------------
        elif item == "doc.xray_knee":
            docs = _standalone_docs_of(extracted, "xray_knee")
            if not docs:
                fail(item, "No knee X-ray report attached")
            else:
                xr = docs[0]
                _check_side(item, xr, operative_side, laterality_kind, fail, mark_unsure)
                xdate = _parse_date(xr.get("date"))
                limit = rules["xray_knee_max_days_before_admission"]
                if xdate is None:
                    mark_unsure(item, f"Knee X-ray has no readable date ({_page_of(xr)}); "
                                      f"cannot confirm it is within {limit} days of admission")
                elif admission is not None:
                    gap = (admission - xdate).days
                    if gap < 0:
                        fail(item, f"Knee X-ray dated {xr.get('date')} is AFTER admission ({_page_of(xr)})")
                    elif gap > limit:
                        fail(item, f"Knee X-ray dated {xr.get('date')} is {gap} days before admission, "
                                   f"older than the {limit}-day limit ({_page_of(xr)})")

        elif item == "doc.conservative_treatment":
            docs = _standalone_docs_of(extracted, "conservative_treatment")
            if not docs:
                # a mention inside the consultation note does not count
                mentions = _docs_of(extracted, "conservative_treatment")
                if mentions:
                    fail(item, "Conservative treatment is only mentioned in the note; "
                               "no separate record attached")
                else:
                    fail(item, "No separate record of conservative treatment attached")
            else:
                weeks = docs[0].get("weeks")
                min_w = rules["conservative_treatment_min_weeks"]
                if _filled(weeks):
                    try:
                        if float(weeks) < min_w:
                            fail(item, f"Conservative treatment record shows only {weeks} weeks "
                                       f"(need at least {min_w}) ({_page_of(docs[0])})")
                    except (TypeError, ValueError):
                        pass

        # ---------------- appendectomy ----------------
        elif item == "doc.abdominal_imaging":
            docs = _standalone_docs_of(extracted, "abdominal_imaging")
            if not docs:
                mentions = _docs_of(extracted, "abdominal_imaging")
                if mentions:
                    fail(item, "Abdominal imaging is only mentioned; the report itself is not attached")
                else:
                    fail(item, "No abdominal ultrasound/CT report attached")

        # ---------------- delivery ----------------
        elif item == "doc.antenatal_record":
            docs = _standalone_docs_of(extracted, "antenatal_record")
            if not docs:
                mentions = _docs_of(extracted, "antenatal_record")
                if mentions:
                    fail(item, "Antenatal details are only in the obstetric note; "
                               "no separate antenatal card attached")
                else:
                    fail(item, "No separate antenatal record (card) attached")

        elif item == "note.lscs_indication":
            # required only for caesarean (filtered in required_items); here we
            # confirm the reason is stated in a note
            notes = _docs_of(extracted, "clinical_note")
            stated = any(n.get("lscs_indication") for n in notes)
            if not stated:
                fail(item, "No medical reason for the caesarean stated in the obstetric note")

        # ---------------- ptca ----------------
        elif item == "doc.ecg":
            docs = _standalone_docs_of(extracted, "ecg")
            if not docs:
                mentions = _docs_of(extracted, "ecg")
                if mentions:
                    fail(item, "ECG is only mentioned in the note; the ECG report itself is not attached")
                else:
                    fail(item, "No ECG report attached")

        elif item == "doc.angiography":
            docs = _standalone_docs_of(extracted, "angiography")
            if not docs:
                mentions = _docs_of(extracted, "angiography")
                if mentions:
                    fail(item, "Angiography is only mentioned; the report itself is not attached")
                else:
                    fail(item, "No coronary angiography report attached")

        # ---------------- estimate line items (cataract/tka/ptca) ----------------
        elif item in rules["estimate_line_item"]:
            keywords = rules["estimate_line_item"][item]
            if not cost_estimates:
                fail(item, "Cost estimate missing, so the required line item cannot be checked")
            else:
                found = any(
                    any(k in (li.get("desc", "") or "").lower() for k in keywords)
                    for li in line_items
                )
                if not found:
                    pretty = keywords[0].upper() if keywords else item
                    fail(item, f"Cost estimate does not list a {pretty} line item")

        else:
            # unknown item id -> be safe, flag for a human
            mark_unsure(item, f"No check implemented for item '{item}'")

    # --------------------------------------------------------------------- #
    # decide the verdict (conservative ordering -- avoid false completes)
    # --------------------------------------------------------------------- #
    if missing:
        status = "incomplete"
        reason = ""
    elif unsure:
        status = "needs_review"
        reason = "; ".join(f"{k}: {v}" for k, v in unsure.items())
    else:
        status = "complete"
        reason = ""

    # keep evidence only for reported findings
    reported = set(missing) | set(unsure)
    evidence = {k: v for k, v in evidence.items() if k in reported}

    return {
        "treatment_type": treatment,
        "status": status,
        "missing_items": missing,
        "evidence": evidence,
        "reason": reason,
    }


def _check_side(item, doc, operative_side, laterality_kind, fail, mark_unsure):
    """Shared laterality check for side-specific documents (biometry / knee X-ray).
    The document must concern the SAME side the form says is being operated on."""
    if not laterality_kind:
        return
    doc_side = _norm_side(doc.get("laterality"))
    if operative_side is None:
        mark_unsure(item, f"Cannot tell which {laterality_kind} the form is for, "
                          f"so cannot confirm the report matches ({_page_of(doc)})")
    elif doc_side is None:
        mark_unsure(item, f"Report does not state which {laterality_kind} it is for "
                          f"({_page_of(doc)})")
    elif doc_side != operative_side:
        fail(item, f"Report is for the {doc_side} {laterality_kind}, but the operation is on "
                   f"the {operative_side} {laterality_kind} ({_page_of(doc)})")


# --------------------------------------------------------------------------- #
# CLI: check one extraction file
# --------------------------------------------------------------------------- #
def main(argv):
    if len(argv) != 2:
        print("usage: python check_packet.py <extracted.json>", file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as fh:
        extracted = json.load(fh)
    verdict = check_packet(extracted)
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
