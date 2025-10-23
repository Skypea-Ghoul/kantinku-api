from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File, Form, Request, Response
from typing import List, Optional
import base64
from .dependencies import get_current_user
from ..models import ProductCreate, ProductOut, UserOut
from ..crud import fetch, insert_product, update, delete, is_product_owner, fetch_products
from ..config import supabase

router = APIRouter(prefix="/products", tags=["Products"])

IMAGE_STORAGE_PATH = "static/images/products"
import os
os.makedirs(IMAGE_STORAGE_PATH, exist_ok=True)

# Helper untuk membuat URL penuh (dari pembahasan sebelumnya)
def _create_full_image_url(request: Request, filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    # URL gambar akan menjadi http://.../static/images/products/namafile.jpg
    return str(request.base_url) + f"static/images/products/{filename}"

@router.get("/", response_model=List[ProductOut])
def get_products(include_inactive: bool = False):
    """
    Mengambil semua produk. Secara default hanya mengambil produk yang aktif.
    Gunakan query parameter `?include_inactive=true` untuk mengambil semua produk
    termasuk yang tidak aktif.
    """
    filters = None
    if not include_inactive:
        # Jika tidak ada permintaan untuk menyertakan yang tidak aktif,
        # maka filter hanya yang aktif.
        filters = {"is_active": True}
    
    # Jika include_inactive=true, filters akan None, dan fetch_products akan mengambil semua.
    products_data = fetch_products(filters=filters) 
    
    products = []
    for p in products_data:
        products.append(ProductOut(**p))
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
def filter_products_by_user(
    user_id: int, 
    # FIX: Terima is_active sebagai query parameter opsional
    is_active: Optional[bool] = None 
):
    """Mengambil produk berdasarkan user ID, dengan opsi filter status aktif."""
    
    # 1. Temukan product_ids milik staff
    product_users = fetch("product_users", filters={"user_id": user_id})
    product_ids = [pu["product_id"] for pu in product_users]
    
    if not product_ids:
        return []
        
    products = []
    
    # 2. Siapkan filter tambahan (hanya jika is_active dikirim)
    product_filter = {}
    if is_active is not None:
        # Jika is_active=True, filter hanya yang aktif.
        # Jika is_active=False, filter hanya yang non-aktif.
        product_filter['is_active'] = is_active
        
    for pid in product_ids:
        # 3. Gabungkan filter ID dan filter status aktif
        combined_filter = {"id": pid}
        combined_filter.update(product_filter) # Tambahkan is_active jika ada
        
        # Ambil detail produk dengan filter gabungan
        res = fetch("products", filters=combined_filter) 
        
        if res:
            products.append(ProductOut(**res[0]))
            
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
    product: ProductCreate,  # Gambar dikirim sebagai string base64
    current_user: UserOut = Depends(get_current_user)
):
    """Membuat produk baru dengan gambar base64."""
    if current_user.role != "staff":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya staff yang bisa membuat produk."
        )
    
    try:
        result = insert_product(product, current_user.id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

@router.put("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: int,
    # FIX: Ubah dari Pydantic model langsung ke Form Data jika Anda menggunakan Form()
    # TAPI: Karena Anda menggunakan product: ProductCreate, kita harus memastikan
    # is_active dapat dimasukkan ke dalam dict yang dikirim ke crud.update.
    # Jika Flutter mengirim data sebagai JSON, signature ini sudah benar
    # dan akan menerima 'is_active'.
    product: ProductCreate, 
    current_user: UserOut = Depends(get_current_user)
):
    """
    Memperbarui produk, termasuk status is_active.
    """
    if not is_product_owner(current_user.id, product_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak memiliki hak untuk mengubah produk ini."
        )
    
    # FIX: Dapatkan data dalam bentuk dictionary, termasuk is_active
    update_data = product.dict(exclude_unset=True)
    
    # Perbarui hanya field yang ada (ini akan mencakup is_active jika dikirim)
    res = update('products', product_id, update_data)
    
    if not res:
        raise HTTPException(status_code=404, detail='Produk tidak ditemukan.')
    return res

@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """
    Menghapus produk. Produk tidak dapat dihapus jika masih ada di keranjang pengguna.
    Hanya pemilik produk yang dapat menghapusnya.
    """
    # 1. Otorisasi: Pastikan user adalah pemilik produk
    if not is_product_owner(current_user.id, product_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak memiliki hak untuk menghapus produk ini."
        )

    # 2. Cek apakah produk ada di dalam keranjang pengguna lain
    cart_item_query = supabase.table("cart_items").select("id", count='exact').eq("product_id", product_id).limit(1).execute()
    
    if cart_item_query.count > 0:
        # Jika ada, jangan hapus, kirim error 409 Conflict
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Produk tidak dapat dihapus karena masih ada di keranjang pengguna."
        )

    supabase.table("product_users").delete().eq("product_id", product_id).execute()

    # 3. Lanjutkan proses penghapusan menggunakan Supabase client
    delete_result = supabase.table("products").delete().eq("id", product_id).execute()

    # 4. Cek apakah ada data yang dihapus. Jika tidak, produk tidak ditemukan.
    if not delete_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Produk dengan ID {product_id} tidak ditemukan."
        )

    # 5. Kembalikan respons 204 No Content yang menandakan sukses tanpa body
    return {"message": f"Produk dengan ID {product_id} berhasil dihapus."}