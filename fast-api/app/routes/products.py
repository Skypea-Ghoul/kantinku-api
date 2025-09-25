from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File, Form
from typing import List
import base64
from .dependencies import get_current_user
from ..models import ProductCreate, ProductOut, UserOut
from ..crud import fetch, insert_product, update, delete, is_product_owner, fetch_products

router = APIRouter(prefix="/products", tags=["Products"])

@router.get("/", response_model=List[ProductOut])
def get_products():
    products_data = fetch_products()
    products = []
    for p in products_data:
        products.append(ProductOut(**p))  # langsung tanpa konversi
    return products

@router.get("/my-products", response_model=List[ProductOut])
async def get_my_products(current_user: UserOut = Depends(get_current_user)):
    product_users = fetch("product_users", filters={"user_id": current_user.id})
    product_ids = [pu["product_id"] for pu in product_users]
    if not product_ids:
        return []
    products = []
    for pid in product_ids:
        res = fetch("products", filters={"id": pid})
        if res:
            products.append(ProductOut(**res[0]))  # langsung tanpa konversi
    return products

@router.get("/filter-by-user", response_model=List[ProductOut])
def filter_products_by_user(user_id: int):
    product_users = fetch("product_users", filters={"user_id": user_id})
    product_ids = [pu["product_id"] for pu in product_users]
    if not product_ids:
        return []
    products = []
    for pid in product_ids:
        res = fetch("products", filters={"id": pid})
        if res:
            products.append(ProductOut(**res[0]))  # langsung tanpa konversi
    return products

@router.get("/{product_id}", response_model=ProductOut)
async def get_product_by_id(
    product_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    if not is_product_owner(current_user.id, product_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak memiliki hak untuk mengakses produk ini."
        )
    res = fetch("products", filters={"id": product_id})
    if not res:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan.")
    return res[0]
@router.post("/", response_model=ProductOut)
async def create_product(
    nama_produk: str = Form(...),
    harga: int = Form(...),
    kategori_id: int = Form(...),
    gambar: str = Form(None),  # Gambar dikirim sebagai string base64
    current_user: UserOut = Depends(get_current_user)
):
    """Membuat produk baru dengan gambar base64."""
    if current_user.role != "staff":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya staff yang bisa membuat produk."
        )

    # Tidak perlu encode, langsung simpan string base64
    product = ProductCreate(
        nama_produk=nama_produk,
        harga=harga,
        kategori_id=kategori_id,
        gambar=gambar
    )
    
    try:
        result = insert_product(product, current_user.id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

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
