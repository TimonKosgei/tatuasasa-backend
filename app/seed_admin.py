# seed_admin.py
import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase_admin = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_ROLE_KEY"],
)

FIRST_ADMIN = {
    "email": "admin@tatuasasa.dev",
    "password": "ChangeThisImmediately123!",
    "full_name": "System Admin",
}

def seed():
    result = supabase_admin.auth.admin.create_user({
        "email": FIRST_ADMIN["email"],
        "password": FIRST_ADMIN["password"],
        "email_confirm": True,
        "user_metadata": {"full_name": FIRST_ADMIN["full_name"]},
    })
    user_id = result.user.id
    print(f"Created auth user: {user_id}")

    supabase_admin.table("profiles").update({
        "role": "admin",
        "status": "approved",
    }).eq("id", user_id).execute()

    print(f"Profile updated to admin. Login with {FIRST_ADMIN['email']} / {FIRST_ADMIN['password']}")

if __name__ == "__main__":
    seed()