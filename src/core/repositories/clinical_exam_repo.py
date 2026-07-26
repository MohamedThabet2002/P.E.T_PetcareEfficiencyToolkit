"""
Clinical exam repository for normalized record-book data.
"""
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection


def _row(q):
    if q.exec() and q.next():
        return q.record()
    return None


def _run(q, what):
    """Executes a prepared write and raises on failure.

    Every clinical-exam write runs inside the caller's visit transaction
    (``visit_repo.add_visit``), so a silent ``exec()`` failure used to commit a
    visit that was missing part of its exam. Raising here lets the caller roll
    the whole entry back instead.
    """
    if not q.exec():
        raise RuntimeError("%s: %s" % (what, q.lastError().text()))
    q.finish()


def save_general_exam(db, visit_id, data):
    if not data:
        return
    q = QSqlQuery(db)
    q.prepare(
        """
        INSERT OR REPLACE INTO visit_general_exam
        (visit_id, weight_value, weight_condition, temperature_value,
         temperature_status, neutered)
        VALUES (?, ?, ?, ?, ?, ?)
        """
    )
    q.addBindValue(visit_id)
    q.addBindValue(data.get('weight_value'))
    q.addBindValue(data.get('weight_condition'))
    q.addBindValue(data.get('temperature_value'))
    q.addBindValue(data.get('temperature_status'))
    q.addBindValue(1 if data.get('neutered') else 0)
    _run(q, "save general exam")


def save_clinical_signs(db, visit_id, data):
    if not data:
        return
    q = QSqlQuery(db)
    q.prepare(
        """
        INSERT OR REPLACE INTO visit_clinical_signs
        (visit_id, energy, appetite, water_intake, urination,
         feces_status, feces_notes,
         vomiting_present, vomiting_frequency,
         coughing_present, coughing_frequency,
         sneezing_present, sneezing_frequency)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
    )
    q.addBindValue(visit_id)
    q.addBindValue(data.get('energy'))
    q.addBindValue(data.get('appetite'))
    q.addBindValue(data.get('water_intake'))
    q.addBindValue(data.get('urination'))
    q.addBindValue(data.get('feces_status'))
    q.addBindValue(data.get('feces_notes'))
    q.addBindValue(1 if data.get('vomiting_present') else 0)
    q.addBindValue(data.get('vomiting_frequency'))
    q.addBindValue(1 if data.get('coughing_present') else 0)
    q.addBindValue(data.get('coughing_frequency'))
    q.addBindValue(1 if data.get('sneezing_present') else 0)
    q.addBindValue(data.get('sneezing_frequency'))
    _run(q, "save clinical signs")


def save_physical_exam(db, visit_id, data):
    if not data:
        return
    q = QSqlQuery(db)
    q.prepare(
        """
        INSERT OR REPLACE INTO visit_physical_exam
        (visit_id, heart_normal, heart_rate, heart_rate_category,
         murmur_left, murmur_right,
         lungs_normal, eyes_normal, ears_normal, nose_throat_normal,
         mouth_teeth_gums_normal, gingivitis_severity,
         abdomen_normal, musculoskeletal_normal, skin_hair_coat_normal)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
    )
    q.addBindValue(visit_id)
    q.addBindValue(1 if data.get('heart_normal') else 0)
    q.addBindValue(data.get('heart_rate'))
    q.addBindValue(data.get('heart_rate_category'))
    q.addBindValue(data.get('murmur_left'))
    q.addBindValue(data.get('murmur_right'))
    q.addBindValue(1 if data.get('lungs_normal') else 0)
    q.addBindValue(1 if data.get('eyes_normal') else 0)
    q.addBindValue(1 if data.get('ears_normal') else 0)
    q.addBindValue(1 if data.get('nose_throat_normal') else 0)
    q.addBindValue(1 if data.get('mouth_teeth_gums_normal') else 0)
    q.addBindValue(data.get('gingivitis_severity'))
    q.addBindValue(1 if data.get('abdomen_normal') else 0)
    q.addBindValue(1 if data.get('musculoskeletal_normal') else 0)
    q.addBindValue(1 if data.get('skin_hair_coat_normal') else 0)
    _run(q, "save physical exam")


def clear_findings(db, visit_id):
    q = QSqlQuery(db)
    q.prepare("DELETE FROM visit_physical_exam_findings WHERE visit_id = ?")
    q.addBindValue(visit_id)
    _run(q, "clear findings")


def clear_conditions(db, visit_id):
    q = QSqlQuery(db)
    q.prepare("DELETE FROM visit_physical_exam_conditions WHERE visit_id = ?")
    q.addBindValue(visit_id)
    _run(q, "clear conditions")


def clear_locations(db, visit_id):
    q = QSqlQuery(db)
    q.prepare("DELETE FROM visit_physical_exam_locations WHERE visit_id = ?")
    q.addBindValue(visit_id)
    _run(q, "clear locations")


def add_finding(db, visit_id, system_name, finding_text):
    if not finding_text:
        return
    q = QSqlQuery(db)
    q.prepare(
        "INSERT INTO visit_physical_exam_findings (visit_id, system_name, finding_text) VALUES (?, ?, ?)"
    )
    q.addBindValue(visit_id)
    q.addBindValue(system_name)
    q.addBindValue(finding_text)
    _run(q, "add finding")


def add_condition(db, visit_id, system_name, condition_text):
    if not condition_text:
        return
    q = QSqlQuery(db)
    q.prepare(
        "INSERT INTO visit_physical_exam_conditions (visit_id, system_name, condition_text) VALUES (?, ?, ?)"
    )
    q.addBindValue(visit_id)
    q.addBindValue(system_name)
    q.addBindValue(condition_text)
    _run(q, "add condition")


def add_location(db, visit_id, location_text):
    if not location_text:
        return
    q = QSqlQuery(db)
    q.prepare(
        "INSERT INTO visit_physical_exam_locations (visit_id, location_text) VALUES (?, ?)"
    )
    q.addBindValue(visit_id)
    q.addBindValue(location_text)
    _run(q, "add location")


def save_routine_tests(db, visit_id, tests):
    q = QSqlQuery(db)
    q.prepare("DELETE FROM visit_routine_tests WHERE visit_id = ?")
    q.addBindValue(visit_id)
    _run(q, "clear routine tests")
    for t in tests or []:
        q = QSqlQuery(db)
        q.prepare(
            "INSERT INTO visit_routine_tests (visit_id, test_name, result) VALUES (?, ?, ?)"
        )
        q.addBindValue(visit_id)
        q.addBindValue(t.get('test_name'))
        q.addBindValue(t.get('result'))
        _run(q, "add routine test")


def save_vaccination_list(db, visit_id, vaccines):
    q = QSqlQuery(db)
    q.prepare("DELETE FROM visit_vaccination_list WHERE visit_id = ?")
    q.addBindValue(visit_id)
    _run(q, "clear vaccination list")
    for v in vaccines or []:
        q = QSqlQuery(db)
        q.prepare(
            "INSERT INTO visit_vaccination_list (visit_id, vaccine_name) VALUES (?, ?)"
        )
        q.addBindValue(visit_id)
        q.addBindValue(v)
        _run(q, "add vaccination")


def save_recommended(db, visit_id, data):
    if not data:
        return
    q = QSqlQuery(db)
    q.prepare("DELETE FROM visit_recommended_tests_treatments WHERE visit_id = ?")
    q.addBindValue(visit_id)
    _run(q, "clear recommended")
    q = QSqlQuery(db)
    q.prepare(
        """
        INSERT INTO visit_recommended_tests_treatments
        (visit_id, xrays, ekg, urinalysis, thyroid_level, follow_up,
         ultrasonic_teeth_cleaning, drug_monitoring, blood_screen, deep_ear_video, other)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
    )
    q.addBindValue(visit_id)
    q.addBindValue(1 if data.get('xrays') else 0)
    q.addBindValue(1 if data.get('ekg') else 0)
    q.addBindValue(1 if data.get('urinalysis') else 0)
    q.addBindValue(1 if data.get('thyroid_level') else 0)
    q.addBindValue(data.get('follow_up'))
    q.addBindValue(1 if data.get('ultrasonic_teeth_cleaning') else 0)
    q.addBindValue(1 if data.get('drug_monitoring') else 0)
    q.addBindValue(1 if data.get('blood_screen') else 0)
    q.addBindValue(1 if data.get('deep_ear_video') else 0)
    q.addBindValue(data.get('other'))
    _run(q, "save recommended")


def save_clinical_exam(db, visit_id, exam_data):
    if not exam_data:
        return
    g = exam_data.get('generalPhysicalExamination', {}) or {}
    weight = g.get('weight', {}) or {}
    temperature = g.get('temperature', {}) or {}
    save_general_exam(db, visit_id, {
        'weight_value': weight.get('value'),
        'weight_condition': weight.get('condition'),
        'temperature_value': temperature.get('value'),
        'temperature_status': temperature.get('status'),
        'neutered': g.get('neutered'),
    })

    s = exam_data.get('clinicalSigns', {}) or {}
    feces = s.get('feces', {}) or {}
    vomiting = s.get('vomiting', {}) or {}
    coughing = s.get('coughing', {}) or {}
    sneezing = s.get('sneezing', {}) or {}
    save_clinical_signs(db, visit_id, {
        'energy': s.get('energy'),
        'appetite': s.get('appetite'),
        'water_intake': s.get('waterIntake'),
        'urination': s.get('urination'),
        'feces_status': feces.get('status'),
        'feces_notes': feces.get('notes'),
        'vomiting_present': vomiting.get('present'),
        'vomiting_frequency': vomiting.get('frequency'),
        'coughing_present': coughing.get('present'),
        'coughing_frequency': coughing.get('frequency'),
        'sneezing_present': sneezing.get('present'),
        'sneezing_frequency': sneezing.get('frequency'),
    })

    pe = exam_data.get('physicalExam', {}) or {}
    heart = pe.get('heart', {}) or {}
    murmur = heart.get('murmur', {}) or {}
    mouth = pe.get('mouthTeethGums', {}) or {}
    save_physical_exam(db, visit_id, {
        'heart_normal': heart.get('normal'),
        'heart_rate': heart.get('heartRate'),
        'heart_rate_category': heart.get('rateCategory'),
        'murmur_left': murmur.get('left'),
        'murmur_right': murmur.get('right'),
        'lungs_normal': (pe.get('lungs', {}) or {}).get('normal'),
        'eyes_normal': (pe.get('eyes', {}) or {}).get('normal'),
        'ears_normal': (pe.get('ears', {}) or {}).get('normal'),
        'nose_throat_normal': (pe.get('noseAndThroat', {}) or {}).get('normal'),
        'mouth_teeth_gums_normal': mouth.get('normal'),
        'gingivitis_severity': mouth.get('gingivitisSeverity'),
        'abdomen_normal': (pe.get('abdomen', {}) or {}).get('normal'),
        'musculoskeletal_normal': (pe.get('musculoskeletal', {}) or {}).get('normal'),
        'skin_hair_coat_normal': (pe.get('skinHairCoat', {}) or {}).get('normal'),
    })
    clear_findings(db, visit_id)
    clear_conditions(db, visit_id)
    clear_locations(db, visit_id)
    for f in (pe.get('lungs', {}) or {}).get('findings', []) or []:
        add_finding(db, visit_id, 'lungs', f)
    for f in (pe.get('eyes', {}) or {}).get('findings', []) or []:
        add_finding(db, visit_id, 'eyes', f)
    for f in (pe.get('ears', {}) or {}).get('findings', []) or []:
        add_finding(db, visit_id, 'ears', f)
    for f in (pe.get('noseAndThroat', {}) or {}).get('findings', []) or []:
        add_finding(db, visit_id, 'noseAndThroat', f)
    for c in (pe.get('mouthTeethGums', {}) or {}).get('conditions', []) or []:
        add_condition(db, visit_id, 'mouthTeethGums', c)
    for c in (pe.get('abdomen', {}) or {}).get('conditions', []) or []:
        add_condition(db, visit_id, 'abdomen', c)
    for c in (pe.get('musculoskeletal', {}) or {}).get('conditions', []) or []:
        add_condition(db, visit_id, 'musculoskeletal', c)
    for c in (pe.get('skinHairCoat', {}) or {}).get('conditions', []) or []:
        add_condition(db, visit_id, 'skinHairCoat', c)
    for l in (pe.get('musculoskeletal', {}) or {}).get('locations', []) or []:
        add_location(db, visit_id, l)
    routine_tests = [
        {'test_name': t.get('testName'), 'result': t.get('result')}
        for t in (exam_data.get('routineTests', []) or [])
    ]
    save_routine_tests(db, visit_id, routine_tests)
    save_vaccination_list(db, visit_id, exam_data.get('vaccinations', []) or [])
    r = exam_data.get('recommendedTestsTreatments', {}) or {}
    save_recommended(db, visit_id, {
        'xrays': r.get('xrays'),
        'ekg': r.get('ekg'),
        'urinalysis': r.get('urinalysis'),
        'thyroid_level': r.get('thyroidLevel'),
        'follow_up': r.get('followUp'),
        'ultrasonic_teeth_cleaning': r.get('ultrasonicTeethCleaning'),
        'drug_monitoring': r.get('drugMonitoring'),
        'blood_screen': r.get('bloodScreen'),
        'deep_ear_video': r.get('deepEarVideo'),
        'other': r.get('other'),
    })


def _fetch_exam_row(visit_id, table):
    db = get_connection()
    q = QSqlQuery(db)
    q.prepare("SELECT * FROM %s WHERE visit_id = ?" % table)
    q.addBindValue(visit_id)
    rec = _row(q)
    q.finish()
    if rec is None:
        return None
    return {rec.fieldName(i): rec.value(i) for i in range(rec.count())}


def _fetch_list(visit_id, table, column):
    db = get_connection()
    q = QSqlQuery(db)
    q.prepare("SELECT %s FROM %s WHERE visit_id = ?" % (column, table))
    q.addBindValue(visit_id)
    out = []
    if q.exec():
        while q.next():
            out.append(q.value(0))
    q.finish()
    return out


def _fetch_pairs(visit_id, table, c1, c2):
    db = get_connection()
    q = QSqlQuery(db)
    q.prepare("SELECT %s, %s FROM %s WHERE visit_id = ?" % (c1, c2, table))
    q.addBindValue(visit_id)
    out = []
    if q.exec():
        while q.next():
            out.append((q.value(0), q.value(1)))
    q.finish()
    return out


def get_clinical_exam(visit_id):
    """Returns the record-book structure for a visit, or None when absent."""
    if not visit_id:
        return None
    general = _fetch_exam_row(visit_id, 'visit_general_exam')
    signs = _fetch_exam_row(visit_id, 'visit_clinical_signs')
    physical = _fetch_exam_row(visit_id, 'visit_physical_exam')
    recommended = _fetch_exam_row(visit_id, 'visit_recommended_tests_treatments')
    findings = _fetch_pairs(visit_id, 'visit_physical_exam_findings', 'system_name', 'finding_text')
    conditions = _fetch_pairs(visit_id, 'visit_physical_exam_conditions', 'system_name', 'condition_text')
    locations = _fetch_list(visit_id, 'visit_physical_exam_locations', 'location_text')
    routine_tests = _fetch_pairs(visit_id, 'visit_routine_tests', 'test_name', 'result')
    vaccinations = _fetch_list(visit_id, 'visit_vaccination_list', 'vaccine_name')

    if not any((general, signs, physical, recommended, findings, conditions,
                locations, routine_tests, vaccinations)):
        return None

    def _by_system(pairs, system):
        return [t for s, t in pairs if s == system]

    def _tri(value):
        # Preserve NULL (nothing recorded) vs an explicit 0 (abnormal) so a
        # partially-recorded exam is not mistaken for a healthy/abnormal one.
        return None if value is None else bool(value)

    physical = physical or {}
    return {
        "generalPhysicalExamination": {
            "weight": {
                "value": (general or {}).get("weight_value"),
                "condition": (general or {}).get("weight_condition"),
            },
            "temperature": {
                "value": (general or {}).get("temperature_value"),
                "status": (general or {}).get("temperature_status"),
            },
            "neutered": bool((general or {}).get("neutered")),
        },
        "clinicalSigns": {
            "energy": (signs or {}).get("energy"),
            "appetite": (signs or {}).get("appetite"),
            "waterIntake": (signs or {}).get("water_intake"),
            "urination": (signs or {}).get("urination"),
            "feces": {
                "status": (signs or {}).get("feces_status"),
                "notes": (signs or {}).get("feces_notes"),
            },
            "vomiting": {
                "present": bool((signs or {}).get("vomiting_present")),
                "frequency": (signs or {}).get("vomiting_frequency"),
            },
            "coughing": {
                "present": bool((signs or {}).get("coughing_present")),
                "frequency": (signs or {}).get("coughing_frequency"),
            },
            "sneezing": {
                "present": bool((signs or {}).get("sneezing_present")),
                "frequency": (signs or {}).get("sneezing_frequency"),
            },
        },
        "routineTests": [{"testName": n, "result": r} for n, r in routine_tests],
        "vaccinations": list(vaccinations),
        "physicalExam": {
            "heart": {
                "normal": _tri(physical.get("heart_normal")),
                "heartRate": physical.get("heart_rate"),
                "rateCategory": physical.get("heart_rate_category"),
                "murmur": {
                    "left": physical.get("murmur_left"),
                    "right": physical.get("murmur_right"),
                },
            },
            "lungs": {"normal": _tri(physical.get("lungs_normal")), "findings": _by_system(findings, 'lungs')},
            "eyes": {"normal": _tri(physical.get("eyes_normal")), "findings": _by_system(findings, 'eyes')},
            "ears": {"normal": _tri(physical.get("ears_normal")), "findings": _by_system(findings, 'ears')},
            "noseAndThroat": {"normal": _tri(physical.get("nose_throat_normal")), "findings": _by_system(findings, 'noseAndThroat')},
            "mouthTeethGums": {"normal": _tri(physical.get("mouth_teeth_gums_normal")),
                               "conditions": _by_system(conditions, 'mouthTeethGums'),
                               "gingivitisSeverity": physical.get("gingivitis_severity")},
            "abdomen": {"normal": _tri(physical.get("abdomen_normal")), "conditions": _by_system(conditions, 'abdomen')},
            "musculoskeletal": {"normal": _tri(physical.get("musculoskeletal_normal")),
                                "conditions": _by_system(conditions, 'musculoskeletal'),
                                "locations": list(locations)},
            "skinHairCoat": {"normal": _tri(physical.get("skin_hair_coat_normal")), "conditions": _by_system(conditions, 'skinHairCoat')},
        },
        "recommendedTestsTreatments": {
            "xrays": bool((recommended or {}).get("xrays")),
            "ekg": bool((recommended or {}).get("ekg")),
            "urinalysis": bool((recommended or {}).get("urinalysis")),
            "thyroidLevel": bool((recommended or {}).get("thyroid_level")),
            "followUp": (recommended or {}).get("follow_up"),
            "ultrasonicTeethCleaning": bool((recommended or {}).get("ultrasonic_teeth_cleaning")),
            "drugMonitoring": bool((recommended or {}).get("drug_monitoring")),
            "bloodScreen": bool((recommended or {}).get("blood_screen")),
            "deepEarVideo": bool((recommended or {}).get("deep_ear_video")),
            "other": (recommended or {}).get("other"),
        },
    }


def save_clinical_exam_for_visit(visit_id, exam_data):
    """Standalone transactional save (used by the Visit Details edit surface)."""
    if not visit_id:
        return False
    db = get_connection()
    db.transaction()
    try:
        save_clinical_exam(db, visit_id, exam_data)
    except Exception:
        db.rollback()
        return False
    if not db.commit():
        db.rollback()
        return False
    return True
