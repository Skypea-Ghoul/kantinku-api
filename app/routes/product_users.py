# file: misal, routers/product_users.py

from fastapi import APIRouter
from typing import List
from ..config import supabase
from ..models import ProductUser # Asumsi Anda punya model Pydantic untuk ini

router = APIRouter(prefix="/product-users", tags=["Product Users"])

@router.get("/", response_model=List[ProductUser])
def get_all_product_users():
    """Mengambil semua relasi antara produk dan user."""
    query = supabase.table("product_users").select("*").execute()
    return query.data