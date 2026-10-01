user_db = {"user_123": {"name": "Ahmet", "role": "developer"}}
def update_user_role(user_id, new_role):
    if user_id in user_db:
        user_data = user_db[user_id] 
        user_data['role'] = new_role
    else:
        print("Kullanıcı bulunamadı.")
update_user_role("user_123", "lead_developer")
