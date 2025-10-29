import os
from fastapi import Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordBearer
from typing import Optional
from jose import JWTError, jwt
from ..models import UserOut
# Anda tidak perlu mengimpor `supabase` di sini jika hanya untuk validasi token

# ✅ PERBAIKAN 1: Muat kunci rahasia dari environment variable
# Buat file .env di root proyek Anda dan tambahkan: SECRET_KEY="secret-key-anda"
# Pastikan Anda sudah menginstal python-dotenv: pip install python-dotenv
# Dan memuatnya di file main.py Anda dengan: from dotenv import load_dotenv; load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY", "kunci-rahasia-default-jika-tidak-ditemukan")
ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Definisikan exception sekali untuk digunakan kembali
credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Tidak dapat memvalidasi kredensial",
    headers={"WWW-Authenticate": "Bearer"},
)

# ✅ PERBAIKAN 2: Buat satu fungsi inti untuk validasi token
def verify_token(token: str) -> UserOut:
    """
    Fungsi inti untuk mendekode token JWT dan mengembalikan data pengguna.
    Memunculkan credentials_exception jika token tidak valid.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Ekstrak data dari payload
        user_id: Optional[int] = payload.get("id")
        username: Optional[str] = payload.get("sub")
        role: Optional[str] = payload.get("role")
        phone: Optional[str] = payload.get("phone")

        # Validasi bahwa semua data penting ada di dalam token
        if any(v is None for v in [user_id, username, role, phone]):
            raise credentials_exception
            
        return UserOut(id=user_id, nama_pengguna=username, role=role, nomor_telepon=phone)

    except JWTError:
        # Jika token tidak bisa di-decode (format salah, expired, dll.)
        raise credentials_exception

# --- DEPENDENCY UNTUK ROUTE HTTP ---
def get_current_user(token: str = Depends(oauth2_scheme)) -> UserOut:
    """
    Dependency untuk endpoint HTTP. Mengambil token dari header 'Authorization'
    dan memvalidasinya.
    """
    return verify_token(token)

# ✅ PERBAIKAN 3: Dependency untuk WebSocket yang lebih tegas
def get_user_from_ws_token(token: Optional[str] = Query(None)) -> UserOut:
    """
    Dependency untuk endpoint WebSocket. Mengambil token dari query parameter
    dan memvalidasinya. Langsung menolak koneksi jika token tidak ada atau tidak valid.
    """
    if token is None:
        # Jika tidak ada token sama sekali
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak ditemukan"
        )
    # Gunakan kembali logika validasi yang sudah ada
    return verify_token(token)