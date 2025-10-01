import os
from supabase import create_client, Client, ClientOptions
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL")
SUPABASE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY")
client_options = ClientOptions(
    # FIX: Atur timeout yang lebih panjang (misalnya 30-60 detik)
    postgrest_client_timeout=60, 
)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY, options=client_options)