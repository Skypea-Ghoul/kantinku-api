from fastapi import APIRouter, HTTPException, status
from typing import List
from ..models import UserLogin, UserOut, UserCreate
from ..crud import fetch, insert, update, delete
from passlib.context import CryptContext

router = APIRouter(prefix="/users", tags=["Users"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@router.get("/", response_model=List[UserOut])
def get_users():
    return fetch("users")

@router.post("/login", response_model=UserOut)
def login_user(user_login: UserLogin):
    users = fetch("users")
    for user in users:
        if (user["nama_pengguna"] == user_login.nama_pengguna and
            user["nomor_telepon"] == user_login.nomor_telepon and
            pwd_context.verify(user_login.password, user["password"])):
            
            # Jika kredensial cocok, kembalikan data user tanpa password
            return user
            
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Nama, nomor telepon, atau password salah"
    )

@router.post("/", response_model=UserOut)
def create_user(user: UserCreate):
    hashed_password = pwd_context.hash(user.password)
    user_data = user.dict()
    user_data["password"] = hashed_password
    result = insert(UserCreate(**user_data))
    if result is None:
        raise HTTPException(status_code=500, detail="Database error")
    return result

@router.put("/{user_id}", response_model=UserOut)
async def edit_user(user_id: int, user: UserCreate):
    user_data = user.dict(exclude_unset=True)
    if "password" in user_data:
        user_data["password"] = pwd_context.hash(user_data["password"])
    res = update('users', user_id, user_data)
    if not res:
        raise HTTPException(404, 'User not found')
    return res

@router.delete("/{user_id}")
async def remove_user(user_id: int):
    res = delete('users', user_id)
    if not res:
        raise HTTPException(404, 'User not found')
    return {"message": f"User dengan id {user_id} telah berhasil dihapus."}