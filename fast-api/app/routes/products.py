from fastapi import APIRouter, HTTPException, status, Depends
from typing import List
from .dependencies import get_current_user
from ..models import ProductCreate, ProductOut, UserOut
from ..crud import fetch, insert_product, update, delete, is_product_owner

router = APIRouter(prefix="/products", tags=["Products"])

@router.get("/", response_model=List[ProductOut])
def get_products():
    """Mendapatkan daftar semua produk."""
    return fetch("products")

@router.post("/", response_model=ProductOut)
def create_product(
    product: ProductCreate,
    current_user: UserOut = Depends(get_current_user)
):
    """Membuat produk baru. Hanya staff yang dapat membuat produk."""
    if current_user.role != "staff":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya staff yang bisa membuat produk."
        )
    result = insert_product(product, current_user.id)
    if result is None:
        raise HTTPException(status_code=500, detail="Database error")
    return result

@router.put("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: int,
    product: ProductCreate,
    current_user: UserOut = Depends(get_current_user)
):
    """Memperbarui produk. Hanya user yang terkait (product_user) yang bisa melakukannya."""
    if not is_product_owner(current_user.id, product_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak memiliki hak untuk mengubah produk ini."
        )
    res = update('products', product_id, product.dict(exclude_unset=True))
    if not res:
        raise HTTPException(status_code=404, detail='Produk tidak ditemukan.')
    return res

@router.delete("/{product_id}")
async def delete_product(
    product_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """Menghapus produk. Hanya user yang terkait (product_user) yang bisa melakukannya."""
    if not is_product_owner(current_user.id, product_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak memiliki hak untuk menghapus produk ini."
        )
    # Hapus dulu dari tabel pivot 'product_users'
    from ..config import supabase
    try:
        supabase.table("product_users").delete().eq('product_id', product_id).execute()
    except Exception as e:
        # Log error, tapi lanjutkan proses
        print(f"Error deleting from product_users: {e}")
    # Baru hapus dari tabel utama
    res = delete('products', product_id)
    if not res:
        raise HTTPException(status_code=404, detail='Produk tidak ditemukan.')
    return {"message": f"Produk dengan ID {product_id} berhasil dihapus."}

@router.get("/{product_id}", response_model=ProductOut)
async def get_product_by_id(
    product_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """
    Mendapatkan produk berdasarkan product_id.
    Hanya user yang terkait (product_user) yang bisa mengakses.
    """
    if not is_product_owner(current_user.id, product_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak memiliki hak untuk mengakses produk ini."
        )
    res = fetch("products", filters={"id": product_id})
    if not res:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan.")
    return res[0]   