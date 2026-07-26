"""Round-trip tests for the normalized clinical exam repository."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.repositories import clinical_exam_repo


SAMPLE = {
    "generalPhysicalExamination": {
        "weight": {"value": 12.5, "condition": "normal"},
        "temperature": {"value": 38.4, "status": "normal"},
        "neutered": True,
    },
    "clinicalSigns": {
        "energy": "decreased",
        "appetite": "normal",
        "waterIntake": "increased",
        "urination": "normal",
        "feces": {"status": "abnormal", "notes": "loose"},
        "vomiting": {"present": True, "frequency": "twice"},
        "coughing": {"present": False, "frequency": ""},
        "sneezing": {"present": False, "frequency": ""},
    },
    "routineTests": [{"testName": "CBC", "result": "pending"}],
    "vaccinations": ["Rabies", "DHLP-P"],
    "physicalExam": {
        "heart": {"normal": False, "heartRate": 120, "rateCategory": "fast",
                  "murmur": {"left": "grade 2", "right": ""}},
        "lungs": {"normal": False, "findings": ["crackles"]},
        "eyes": {"normal": True, "findings": []},
        "ears": {"normal": True, "findings": []},
        "noseAndThroat": {"normal": True, "findings": []},
        "mouthTeethGums": {"normal": False, "conditions": ["tartar"], "gingivitisSeverity": "mild"},
        "abdomen": {"normal": True, "conditions": []},
        "musculoskeletal": {"normal": False, "conditions": ["stiff"], "locations": ["left hip"]},
        "skinHairCoat": {"normal": True, "conditions": []},
    },
    "recommendedTestsTreatments": {
        "xrays": True, "ekg": False, "urinalysis": True, "thyroidLevel": False,
        "followUp": "2 weeks", "ultrasonicTeethCleaning": True, "drugMonitoring": False,
        "bloodScreen": True, "deepEarVideo": False, "other": "dental diet",
    },
}


def _make_visit(repos, entity_factory):
    cid = entity_factory["make_client"]()
    pid = entity_factory["make_pet"](cid)
    return repos["visit"].add_visit("2026-01-10", "checkup", False, "n", pet_id=pid)


def test_save_and_get_round_trip(fresh_db, repos, entity_factory):
    visit_id = _make_visit(repos, entity_factory)
    assert isinstance(visit_id, int)

    assert clinical_exam_repo.save_clinical_exam_for_visit(visit_id, SAMPLE) is True

    got = clinical_exam_repo.get_clinical_exam(visit_id)
    assert got is not None
    assert got["generalPhysicalExamination"]["weight"] == {"value": 12.5, "condition": "normal"}
    assert got["generalPhysicalExamination"]["neutered"] is True
    assert got["clinicalSigns"]["vomiting"] == {"present": True, "frequency": "twice"}
    assert got["clinicalSigns"]["feces"] == {"status": "abnormal", "notes": "loose"}
    assert got["routineTests"] == [{"testName": "CBC", "result": "pending"}]
    assert sorted(got["vaccinations"]) == ["DHLP-P", "Rabies"]
    assert got["physicalExam"]["heart"]["murmur"]["left"] == "grade 2"
    assert got["physicalExam"]["lungs"]["findings"] == ["crackles"]
    assert got["physicalExam"]["mouthTeethGums"]["conditions"] == ["tartar"]
    assert got["physicalExam"]["mouthTeethGums"]["gingivitisSeverity"] == "mild"
    assert got["physicalExam"]["musculoskeletal"]["conditions"] == ["stiff"]
    assert got["physicalExam"]["musculoskeletal"]["locations"] == ["left hip"]
    assert got["recommendedTestsTreatments"]["xrays"] is True
    assert got["recommendedTestsTreatments"]["followUp"] == "2 weeks"


def test_get_returns_none_when_no_exam(fresh_db, repos, entity_factory):
    visit_id = _make_visit(repos, entity_factory)
    assert clinical_exam_repo.get_clinical_exam(visit_id) is None


def test_save_is_idempotent_replace(fresh_db, repos, entity_factory):
    visit_id = _make_visit(repos, entity_factory)
    clinical_exam_repo.save_clinical_exam_for_visit(visit_id, SAMPLE)
    clinical_exam_repo.save_clinical_exam_for_visit(visit_id, SAMPLE)
    got = clinical_exam_repo.get_clinical_exam(visit_id)
    assert len(got["physicalExam"]["lungs"]["findings"]) == 1


def test_visit_add_accepts_clinical_exam(fresh_db, repos, entity_factory):
    cid = entity_factory["make_client"]()
    pid = entity_factory["make_pet"](cid)
    visit_id = repos["visit"].add_visit(
        "2026-01-10", "checkup", False, "n", pet_id=pid, clinical_exam=SAMPLE)
    assert isinstance(visit_id, int)
    assert clinical_exam_repo.get_clinical_exam(visit_id) is not None


def _bad_exam():
    """An exam that violates visit_general_exam's weight_condition CHECK."""
    bad = dict(SAMPLE)
    bad["generalPhysicalExamination"] = {
        "weight": {"value": 5.0, "condition": "not-a-real-condition"},
    }
    return bad


def test_save_clinical_exam_raises_on_a_bad_section(fresh_db, repos, entity_factory):
    """A failing write must surface, not commit a visit missing its exam."""
    import pytest
    visit_id = _make_visit(repos, entity_factory)
    with pytest.raises(RuntimeError):
        clinical_exam_repo.save_clinical_exam(fresh_db, visit_id, _bad_exam())


def test_add_visit_rolls_back_when_the_exam_fails(fresh_db, repos, entity_factory):
    """A clinical-exam failure rolls back the whole visit (no visit row left)."""
    cid = entity_factory["make_client"]()
    pid = entity_factory["make_pet"](cid)
    result = repos["visit"].add_visit(
        "2026-01-10", "checkup", False, "n", pet_id=pid, clinical_exam=_bad_exam())
    assert result is None
    assert repos["visit"].get_recent_visits_for_client(cid) == []

