from fastapi import APIRouter, HTTPException, status
from typing import List
from ..models import Category, CategoryCreate, CategoryOut
from ..crud import fetch_categories, insert_category, update, delete

router = APIRouter(prefix="/categories", tags=["Categories"])

@router.get("/", response_model=List[CategoryOut])
def get_categories():
    """Mendapatkan daftar semua kategori."""
    return fetch_categories()

@router.get("/{kategori_id}", response_model=CategoryOut)
def get_category_detail(kategori_id: int):
    """Mendapatkan detail satu kategori."""
    res = fetch_categories({"id": kategori_id})
    if not res:
        raise HTTPException(status_code=404, detail="Kategori tidak ditemukan")
    return res[0]

@router.post("/", response_model=CategoryOut)
def create_category(kategori: CategoryCreate):
    """Membuat kategori baru."""
    res = insert_category(kategori)
    if not res:
        raise HTTPException(status_code=500, detail="Database error")
    return res

@router.put("/{kategori_id}", response_model=CategoryOut)
def update_category(kategori_id: int, kategori: CategoryCreate):
    """Memperbarui kategori."""
    res = update('categories', kategori_id, kategori.dict(exclude_unset=True))
    if not res:
        raise HTTPException(status_code=404, detail="Kategori tidak ditemukan")
    return res

@router.delete("/{kategori_id}")
def remove_category(kategori_id: int):
    """Menghapus kategori."""
    res = delete('categories', kategori_id)
    if not res:
        raise HTTPException(status_code=404, detail="Kategori tidak ditemukan")
    return {"message": f"Kategori dengan ID {kategori_id} berhasil dihapus."}