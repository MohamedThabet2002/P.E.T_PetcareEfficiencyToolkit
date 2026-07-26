"""Tests for the card-based PetInfoDialog (health indicator, trimmed cards)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src.core.repositories.pet_repo as pet_repo
from src.ui.dialogs.info_dialogs import PetInfoDialog


def _admin_user(user_id=1):
    return {"user_id": user_id, "username": "admin", "roles": ["admin"]}


def _labels(dlg):
    out = []
    stack = [dlg]
    while stack:
        w = stack.pop()
        text = getattr(w, "text", None)
        if text is not None:
            try:
                t = text()
                if t:
                    out.append(t)
            except Exception:
                pass
        stack.extend(w.children())
    return out


def _seed_pet(repos, health_status=None):
    cid = repos["client"].add_client("Ali Hassan", "0500123456")
    pid = pet_repo.add_pet("Rexy", "Dog", "Lab", "M", 30, 30.0, cid)
    if health_status:
        pet_repo.update_pet(pid, "Rexy", "Dog", "Lab", "M", 30, 30.0, cid,
                            health_status=health_status)
    return pid


def test_pet_details_drops_vaccination_and_medication_cards(qapp, fresh_db, repos):
    pid = _seed_pet(repos)
    dlg = PetInfoDialog({"pet_id": pid, "pet_name": "Rexy"}, current_user=_admin_user())
    labels = _labels(dlg)
    assert "Vaccinations" not in labels
    assert "Medications" not in labels
    assert not hasattr(dlg, "_vaccinations_body")
    assert not hasattr(dlg, "_medications_body")


def test_pet_details_no_longer_shows_weight(qapp, fresh_db, repos):
    pid = _seed_pet(repos)
    dlg = PetInfoDialog({"pet_id": pid, "pet_name": "Rexy"}, current_user=_admin_user())
    assert not any(t.startswith("Weight") for t in _labels(dlg))
    dlg._toggle_edit(True)
    assert not hasattr(dlg, "_weight_edit")


def test_pet_details_health_card_shows_derived_status(qapp, fresh_db, repos):
    pid = _seed_pet(repos)
    dlg = PetInfoDialog({"pet_id": pid, "pet_name": "Rexy"}, current_user=_admin_user())
    labels = _labels(dlg)
    assert "Current Status:" in labels
    assert "Derived from latest exam" in labels


def test_pet_details_health_edit_offers_manual_statuses(qapp, fresh_db, repos):
    pid = _seed_pet(repos)
    dlg = PetInfoDialog({"pet_id": pid, "pet_name": "Rexy"}, current_user=_admin_user())
    dlg._toggle_edit(True)
    choices = [dlg._health_edit.itemData(i) for i in range(dlg._health_edit.count())]
    assert "Healthy" in choices
    assert "Recovering" in choices
    assert "Critical" in choices
    assert "Diseased" in choices
    assert "Died" in choices
