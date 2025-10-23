from fastapi import Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordBearer
from typing import Optional
from jose import JWTError, jwt
from ..models import UserOut
from ..config import supabase  # import supabase client

SECRET_KEY = "secret-key-anda"
ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def get_current_user(token: str = Depends(oauth2_scheme)) -> UserOut:
    # =======================================================================
    # PERBAIKAN DI SINI: Ganti placeholder (...) dengan definisi yang lengkap
    # =======================================================================
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Tidak dapat memvalidasi kredensial",
        headers={"WWW-Authenticate": "Bearer"},
    )
    # =======================================================================
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        user_id: int = payload.get("id")
        role: str = payload.get("role")
        phone: str = payload.get("phone")

        if username is None or user_id is None or role is None or phone is None:
            raise credentials_exception
            
        return UserOut(id=user_id, nama_pengguna=username, role=role, nomor_telepon=phone)

    except JWTError:
        raise credentials_exception

# Dependensi untuk WebSocket
async def get_current_user_from_ws(
    token: Optional[str] = Query(None)
) -> Optional[UserOut]:
    if token is None:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        user_id: int = payload.get("id")
        role: str = payload.get("role")
        phone: str = payload.get("phone")

        if username is None or user_id is None or role is None or phone is None:
            return None
            
        return UserOut(id=user_id, nama_pengguna=username, role=role, nomor_telepon=phone)
    except JWTError:
        return None