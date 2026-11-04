---
name: corvus-checklist
description: Use when checking whether a Corvus Health pre-authorisation packet is complete. Applies Meena's checklist for the five treatment types (cataract, tka, appendectomy, delivery, ptca) to a packet you have read, and returns status (complete / incomplete / needs_review) and the exact missing item IDs. Use after reading a packet PDF, before writing the output record.
---

# corvus-checklist

Meena Joshi's completeness checklist for pre-authorisation packets, packaged
so the prototype applies it the same way every time.

**The split that matters:** *you* (the model) **read** the scanned packet and
write down what is on the pages. **Code** (`check_packet.py`) **decides**
whether each checklist item is satisfied. Never decide completeness by reading
— extract faithfully, then let the code judge. This keeps the verdict testable
and stops "looks right" from becoming "is right".

**Safety:** this skill reports completeness only. It never approves, rejects,
or predicts the outcome of a request. A processor decides.

## How to use it

1. Read every page of the packet PDF.
2. Write an **extraction JSON** (schema below) describing what you found —
   which documents are present, the form fields, dates, the eye/knee, the
   totals. Record only what is on the page. If you cannot read something a
   check needs, do **not** guess: put it in `uncertain`.
3. Run the checker on your extraction:

   ```bash
   python .claude/skills/corvus-checklist/check_packet.py <extraction.json>
   ```

   or, in code:

   ```python
   from check_packet import check_packet, load_checklist
   verdict = check_packet(extracted, load_checklist())
   ```

4. The checker returns `status`, `missing_items` (Meena's IDs), `evidence`
   and `reason`. Combine it with the extracted `fields` to build the final
   record (see `CLAUDE.md`).

The checklist data lives in `checklist.json` — the single source of truth,
exported from Meena's spreadsheet. `check_packet.py` reads it; don't hard-code
rules elsewhere.

## What the checker enforces (every rule on the checklist)

- The **required items per treatment type** (common items + treatment extras).
- **Date limits:** consultation note within 30 days before a *planned*
  admission (an emergency admission note has no window); knee X-ray within
  90 days before admission.
- **Cost agreement:** estimate total within 10% of the form's estimated cost;
  estimate must be on hospital letterhead and signed.
- **ICD-10 consistency:** the code's chapter must match the treatment
  (e.g. cataract → H25/H26/H28, tka → M17, ptca → I20–I25).
- **Same eye / knee throughout:** the side-specific report (biometry, knee
  X-ray) must concern the same side the form says is being operated on.
  (Design choice: the form's `procedure` side is authoritative; a report for
  the other side fails *that document's* item.)
- **Standalone documents:** ECG, angiography, abdominal imaging, antenatal
  record and the conservative-treatment record must be the report itself, not
  a mention inside another note (`mentions_only: true` does not satisfy them).
- **Member ID:** filled in and legible, and matching the ID card (names may
  confirm when IDs differ by an obvious typo). There is no ClaimCore lookup
  yet — that is Session 4.
- **Caesarean only:** `note.lscs_indication` is required only when
  `delivery_mode == "caesarean"`.

## The extraction JSON schema (what the model writes)

```json
{
  "packet_id": "D01",
  "pages": 5,
  "treatment_type": "cataract",          // cataract | tka | appendectomy | delivery | ptca
  "form": {
    "present": true,
    "page": 1,
    "patient_name": "Neha Yadav",
    "member_id": "CVH36109074",
    "hospital_id": "CVN-RJ-0105",
    "doctor_name": "Dr Ritu Bhargava",
    "doctor_reg_no": "RMC/2006/76698",
    "diagnosis": "Senile nuclear cataract, right eye",
    "icd10": "H25.1",
    "procedure": "Phacoemulsification with IOL, right eye",
    "admission_type": "planned",         // planned | emergency
    "admission_date": "2026-10-17",      // YYYY-MM-DD
    "length_of_stay": 1,
    "estimated_cost": 44000,             // whole rupees, number
    "doctor_signature_present": true,
    "patient_signature_present": true,
    "laterality": "right",               // eye/knee side, if relevant; else null
    "delivery_mode": null                // "normal" | "caesarean" for delivery
  },
  "documents": [
    {"type": "id_card", "page": 2, "name": "Neha Yadav", "member_id": "CVH36109074", "dob": "1967-02-02"},
    {"type": "clinical_note", "page": 3, "date": "2026-10-01", "laterality": "right", "lscs_indication": false},
    {"type": "cost_estimate", "page": 4, "total": 44000, "on_letterhead": true, "signed": true,
     "line_items": [{"desc": "Lens: Monofocal hydrophobic foldable IOL", "amount": 12000}]},
    {"type": "biometry", "page": 5, "laterality": "right", "details": "IOL power +21.5 D"}
  ],
  "uncertain": []                        // [{"item": "form.diagnosis", "reason": "handwritten, not legible"}]
}
```

### Document `type` values the checker understands
`id_card`, `clinical_note`, `cost_estimate`, `biometry`, `xray_knee`,
`conservative_treatment`, `abdominal_imaging`, `antenatal_record`, `ecg`,
`angiography`.

### Fields the checks read
- `clinical_note`: `date`, and `lscs_indication` (bool) for caesareans.
- `cost_estimate`: `total`, `on_letterhead`, `signed`, `line_items[].desc`.
- `biometry` / `xray_knee`: `laterality`; `xray_knee` also `date`.
- `conservative_treatment`: `weeks`.
- Any document that is only referenced inside another note (not attached as
  its own report): set `"mentions_only": true`.

### When to use `uncertain`
Put an item in `uncertain` when a scan is illegible or a key field cannot be
read — a handwritten diagnosis you cannot make out, a date you cannot resolve,
a smudged member ID. The checker turns required-item uncertainty into
`needs_review` with your reason, rather than risk a false "complete".

## Verdict rules (in `check_packet.py`)

1. If any required item is definitely missing or invalid → **incomplete**
   (with the item IDs).
2. Else if any required item is uncertain → **needs_review** (with the reason).
3. Else → **complete**.

A false complete (saying "complete" when something is missing) is the worst
error, so uncertainty never resolves to "complete".
