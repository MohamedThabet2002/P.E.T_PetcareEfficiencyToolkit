"""
Clinical Service to handle complex multi-entity operations.
Coordinates between Client, Pet, and Visit repositories.
"""

#====================================== IMPORTS =======================================================#

import src.core.repositories.client_repo as client_repo
import src.core.repositories.pet_repo as pet_repo
import src.core.repositories.visit_repo as visit_repo

#============================== TRANSLATABLE STRINGS ===================================================#

TR_CLIENT_CREATION_ERROR = "Failed to create or identify client."
TR_PET_CREATION_ERROR = "Failed to create or update pet."

#============================================== CODE =====================================================#

def process_full_clinical_entry(owner_data, pet_data, visit_data, items=None):
    """
    Orchestrates the creation of a Client, Pet, and Visit in one flow.
    Returns (success, result_id_or_error_msg).
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
        client_id = client_repo.add_client(owner_name, phone)
    elif owner_data.get('new_phone'):
        client_repo.update_client(client_id, owner_name, owner_data['new_phone'])
    
    if not client_id:
        return False, TR_CLIENT_CREATION_ERROR
    
    # --- 2. Pet Handling ---
    pet_id = None
    if pet_data and pet_data.get('name'): # Only process pet data if a pet name is provided
        pet_name = pet_data['name'].strip().capitalize()
        species, breed = pet_data['species'], pet_data['breed']
        gender, age, weight = pet_data['gender'], pet_data['age'], pet_data['weight']
        
        existing_pet = pet_repo.get_existing_pet(pet_name, species, breed, gender, client_id)
        
        if existing_pet:
            pet_id = existing_pet["id"]
            pet_repo.update_pet_details(pet_id, age, weight)
        else:
            pet_id = pet_repo.add_pet(pet_name, species, breed, gender, age, weight, client_id)
    
        if not pet_id:
            return False, TR_PET_CREATION_ERROR
    
    # --- 3. Visit Handling ---
    result = visit_repo.add_visit(
        visit_data['date'], 
        visit_data['diagnosis'], 
        visit_data['is_consult'], 
        visit_data['notes'], 
        pet_id=pet_id,
        items=items,
        client_id=client_id
    )
    
    if isinstance(result, str) and result.startswith("STOCK_ERROR"):
        return False, result
        
    return bool(result), result