"""
Clinical Service to handle complex multi-entity operations.
Coordinates between Client, Pet, and Visit repositories.
"""

#====================================== IMPORTS =======================================================#

import src.core.repositories.client_repo as client_repo
import src.core.repositories.pet_repo as pet_repo
import src.core.repositories.visit_repo as visit_repo
import src.core.repositories.user_repo as user_repo
import src.core.repositories.followup_repo as followup_repo

#============================================== CODE =====================================================#

def process_full_clinical_entry(owner_data, pet_data, visit_data, items=None,
                                health_stats=None, tests=None, treatments=None,
                                vaccinations=None, medications=None,
                                current_user=None, doctor_id=None, packages=None,
                                ids_out=None, clinical_exam=None):
    """
    Orchestrates the creation of a Client, Pet, and Visit in one flow.
    Returns (success, result_id_or_error_msg).

    ``ids_out`` (optional dict) is forwarded to ``visit_repo.add_visit`` and
    receives the created ``visit_id`` / ``receipt_id``, for callers that must
    print or open the visit's receipt afterwards.
    """
    # --- 1. Client Handling ---
    owner_name = owner_data['name'].strip().title()
    phone = owner_data['phone'].strip()
    client_id = owner_data.get('merge_id')
    
    # If no explicit ID, try to identify existing client by name and phone
    if not client_id:
        existing_clients = client_repo.get_clients_by_name_exact(owner_name)
        for client in existing_clients:
            if client['phone_number'] == phone:
                client_id = client['client_id']
                break
    
    # Create new if not found, or update if phone changed for a merged client
    if not client_id:
        client_id = client_repo.add_client(
            owner_name, phone,
            audit_user_id=(current_user or {}).get("user_id"),
        )
    elif owner_data.get('new_phone'):
        client_repo.update_client(
            client_id, owner_name, owner_data['new_phone'],
            audit_user_id=(current_user or {}).get("user_id"),
        )
    
    if not client_id:
        return False, "Failed to create or identify client."
    
    # --- 2. Pet Handling ---
    pet_id = None
    if pet_data and pet_data.get('name'): # Only process pet data if a pet name is provided
        pet_name = pet_data['name'].strip().capitalize()
        species, breed = pet_data['species'], pet_data['breed']
        gender, age, weight = pet_data['gender'], pet_data['age'], pet_data['weight']
        
        # A pet is identified by its name for that owner - the same rule the
        # Add Visit dialog uses when it fills the form - so every edited field
        # (breed, species, gender included) lands on the existing row instead of
        # being dropped or duplicated.
        existing_pets = pet_repo.get_pets_by_name_for_client(client_id, pet_name)

        if existing_pets:
            pet_id = existing_pets[0]["pet_id"]
            pet_repo.update_pet(
                pet_id, pet_name, species, breed, gender, age, weight, client_id,
                audit_user_id=(current_user or {}).get("user_id"),
            )
        else:
            pet_id = pet_repo.add_pet(
                pet_name, species, breed, gender, age, weight, client_id,
                audit_user_id=(current_user or {}).get("user_id"),
            )
    
        if not pet_id:
            return False, "Failed to create or update pet."
    
    # --- 3. Visit Handling ---
    result = visit_repo.add_visit(
        visit_data['date'], 
        visit_data['diagnosis'], 
        visit_data['is_consult'], 
        visit_data['notes'], 
        pet_id=pet_id,
        items=items,
        client_id=client_id,
        reason_for_visit=visit_data.get('reason_for_visit', ""),
        health_stats=health_stats,
        tests=tests,
        treatments=treatments,
        vaccinations=vaccinations,
        medications=medications,
        doctor_id=(doctor_id if doctor_id is not None else
                   visit_data.get('doctor_id') if visit_data else None) or
                  user_repo.get_doctor_id(current_user),
        audit_user_id=(current_user or {}).get("user_id"),
        packages=packages,
        discount=visit_data.get('discount', 0.0),
        paid_amount=visit_data.get('paid_amount'),
        payment_notes=visit_data.get('payment_notes', ""),
        payment_method=visit_data.get('payment_method', "Cash"),
        ids_out=ids_out,
        clinical_exam=clinical_exam or visit_data.get('clinical_exam'),
    )
    
    if isinstance(result, str) and result.startswith("STOCK_ERROR"):
        return False, result
        
    return bool(result), result


def schedule_followup_after_entry(owner_name, owner_phone, visit_date, followup_date, notes=""):
    """Schedules a follow-up for the visit that was just recorded for this owner.

    Resolves the owner's latest visit for ``visit_date`` and adds a follow-up
    against it. Returns the followup_id on success, or None if the owner/visit
    could not be located or the follow-up insert failed.
    """
    if not owner_name or not followup_date:
        return None

    owner_name = owner_name.strip().title()
    existing_clients = client_repo.get_clients_by_name_exact(owner_name)
    client = next(
        (c for c in existing_clients
         if c.get("phone_number") == owner_phone or not owner_phone),
        None,
    )
    if client is None:
        return None

    visit_id = visit_repo.get_latest_visit_id_for_client(client["client_id"], visit_date)
    if not visit_id:
        return None

    return followup_repo.add_followup(visit_id, followup_date, notes=notes)
