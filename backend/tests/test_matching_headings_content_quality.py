"""Regression checks for the internally reviewed Phase 6 heading corrections."""
import json
from pathlib import Path


def test_transfer_and_review_headings_cover_paragraph_claims():
    path = Path(__file__).resolve().parents[1] / "app/content/ielts_matching_headings_diagnostics.json"
    pack = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "ielts-mh-academic-main-transfer": ["cooler routes", "calibrating", "public transport"],
        "ielts-mh-academic-main-review": ["cooperation", "confidence", "knowledge"],
        "ielts-mh-academic-keyword-transfer": ["plant responses", "rainfall response", "survival"],
        "ielts-mh-academic-keyword-review": ["purchases", "online reservations", "practical limits"],
        "ielts-mh-gt-main-transfer": ["continuity", "patient updates", "service consistency"],
        "ielts-mh-gt-main-review": ["neighbourhood ties", "new connections", "safe and requested"],
        "ielts-mh-gt-keyword-transfer": ["people away from home", "before parcels", "Thursday hours"],
        "ielts-mh-gt-keyword-review": ["commute", "inspections and access", "will be reviewed"],
    }
    found = {}
    for questions in pack["questions"].values():
        for question in questions:
            if question["id"] not in expected:
                continue
            group = question["reading_group"]
            options = {option["id"]: option["text"] for option in group["display"]["options"]}
            answers = group["private_rules"]["answers"]
            assert group["display"]["passage"]["content_version"] == "2"
            assert group["private_rules"]["rules_version"] == "2"
            assert "independent editorial review pending" in group["provenance"]["review_status"]
            for index, phrase in enumerate(expected[question["id"]], 1):
                assert phrase in options[answers[f"item-{index}"]]
                assert not group["private_rules"]["explanations"][f"item-{index}"].startswith(
                    "This heading captures the paragraph"
                )
            found[question["id"]] = True
    assert set(found) == set(expected)
