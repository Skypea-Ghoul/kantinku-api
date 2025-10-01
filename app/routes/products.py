from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File, Form
from typing import List, Optional
import base64
from .dependencies import get_current_user
from ..models import ProductCreate, ProductOut, UserOut
from ..crud import fetch, insert_product, update, delete, is_product_owner, fetch_products

router = APIRouter(prefix="/products", tags=["Products"])

@router.get("/", response_model=List[ProductOut])
def get_products():
    products_data = fetch_products(filters={"is_active": True}) 
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

@router.delete("/{product_id}")
async def delete_product(
    product_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """
    FIX: Melakukan Soft Delete (menyetel is_active=False) untuk menjaga integritas data.
    """
    if not is_product_owner(current_user.id, product_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak memiliki hak untuk menghapus produk ini."
        )

    # Kita TIDAK menghapus dari tabel product_users atau product_items di sini.
    # Kita hanya menonaktifkan produk.
    
    # Asumsi: crud.update dapat memperbarui field is_active
    update_data = {"is_active": False}
    
    res = update('products', product_id, update_data)
    
    if not res:
        raise HTTPException(status_code=404, detail='Produk tidak ditemukan.')
        
    return {"message": f"Produk dengan ID {product_id} berhasil dinonaktifkan."}