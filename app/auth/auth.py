from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import timedelta, datetime
from ..config import supabase   
from ..routes.dependencies import get_current_user
from ..models import UserCreate, UserOut
from ..routes.dependencies import SECRET_KEY, ALGORITHM

router = APIRouter(prefix="/auth", tags=["Auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def create_access_token(data: dict, expires_delta: timedelta = timedelta(hours=24)):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

@router.post("/register", response_model=UserOut)
def register(user: UserCreate):
    # Cek apakah username sudah ada (tidak case-sensitive)
    # PERBAIKAN: Ganti .eq() dengan .ilike()
    existing_query = supabase.table("users").select("id", count='exact').ilike("nama_pengguna", user.nama_pengguna).execute()
    
    # Cek count untuk performa yang lebih baik
    if existing_query.count > 0:
        raise HTTPException(status_code=400, detail="Username sudah terdaftar")
        
    hashed_password = pwd_context.hash(user.password)
    user_data = user.dict()
    user_data["password"] = hashed_password
    result = supabase.table("users").insert(user_data).execute().data
    if not result:
        raise HTTPException(status_code=500, detail="Gagal mendaftarkan pengguna")
        
    return UserOut(**result[0])

@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # Cari user di Supabase
    user_query = supabase.table("users").select("*").eq("nama_pengguna", form_data.username).execute()
    if not user_query.data:
        raise HTTPException(status_code=400, detail="Username tidak ditemukan")
    
    # `user_query.data` adalah list, ambil elemen pertamanya
    user = user_query.data[0] 
    
    # HAPUS BARIS INI KARENA MENYEBABKAN KeyError: 0
    # user = user[0] 

    if not pwd_context.verify(form_data.password, user["password"]):
        raise HTTPException(status_code=400, detail="Password salah")

    # Buat token dengan data yang lengkap
    token_data = {
        "sub": user["nama_pengguna"],
        "id": user["id"],
        "role": user["role"],
        "phone": user["nomor_telepon"]
    }
    access_token = create_access_token(data=token_data)
    
    # Cukup satu return statement
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/profile", response_model=UserOut)
def get_profile(current_user=Depends(get_current_user)):
    return current_user