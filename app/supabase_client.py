import os
from dotenv import load_dotenv
from supabase import create_client, Client
 
load_dotenv()
 
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

# anon key client — respects RLS, this is what auth endpoints use
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

#admin
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)