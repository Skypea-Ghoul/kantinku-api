from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from ..models import UserOut
from ..config import supabase  # import supabase client

SECRET_KEY = "secret-key-anda"
ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def get_current_user(token: str = Depends(oauth2_scheme)) -> UserOut:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Tidak dapat memvalidasi kredensial",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        # Query user dari Supabase (ambil semua, bukan single)
        result = supabase.table("users").select("*").eq("nama_pengguna", username).execute()
        user_list = result.data
        if not user_list or len(user_list) == 0:
            raise credentials_exception
        # Ambil user pertama jika ada duplikat
        return UserOut(**user_list[0])
    except JWTError:
        raise credentials_exception