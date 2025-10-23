from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# Users
# class User(BaseModel):
#     id: Optional[int]
#     nama_pengguna: str
#     nomor_telepon: str
#     role: str

# class UserCreate(BaseModel):
#     nama_pengguna: str
#     nomor_telepon: str
#     role: str

# class UserOut(User):
#     id: int
# Users
class User(BaseModel):
    id: Optional[int]
    nama_pengguna: str
    nomor_telepon: str
    role: str
    password: str  # tambahkan password

class UserCreate(BaseModel):
    nama_pengguna: str
    nomor_telepon: str
    role: str
    password: str  # tambahkan password

class UserOut(BaseModel):
    id: int
    nama_pengguna: str
    nomor_telepon: str
    role: str
    # password tidak perlu di sini

class UserLogin(BaseModel):
    nama_pengguna: str
    nomor_telepon: str
    password: str

# Kategori
class Category(BaseModel):
    id: Optional[int]
    kategori: str

class CategoryCreate(BaseModel):
    kategori: str

class CategoryOut(Category):
    id: int

# Product
class Product(BaseModel):
    id: Optional[int]
    nama_produk: str
    harga: int
    kategori_id: int
    deskripsi: Optional[str] = None 
    gambar: Optional[str] = None
    # FIX: Tambahkan field is_active
    is_active: bool = True 

class ProductCreate(BaseModel):
    nama_produk: str
    harga: int
    kategori_id: int
    deskripsi: Optional[str] = None 
    gambar: Optional[str] = None
    # FIX: Tambahkan field is_active
    is_active: bool = True 


class ProductOut(Product):
    id: int

# CartItems (Pivot)
class CartItem(BaseModel):
    id: Optional[int]
    user_id: int
    product_id: int
    jumlah: int

class CartItemCreate(BaseModel):
    product_id: int
    jumlah: int

class CartItemOut(CartItem):
    id: int

# ProductUsers (Pivot)
class ProductUser(BaseModel):
    id: Optional[int]
    user_id: int
    product_id: int

# OrderItems
class OrderItem(BaseModel):
    id: Optional[int]
    order_id: int
    product_id: int
    jumlah: int
    harga_unit: float
    subtotal: float
    status: str = "paid" # Status default saat item dibuat
    class Config:
        orm_mode = True

# Orders
class Order(BaseModel):
    id: Optional[int]
    user_id: int
    status: str
    total_harga: float
    tanggal_pesanan: Optional[str] = Field(None, description="Waktu pesanan dibuat dalam format string")
    order_items: List[OrderItem] = [] 
    snap_redirect_url: Optional[str] = None
    class Config:
        orm_mode = True

class SalesSummary(BaseModel):
    tanggal: str
    total_penjualan: float

class ProductSalesSummary(BaseModel):
    nama_produk: str
    jumlah_pesanan: int

# Payments
class Payment(BaseModel):
    id: Optional[int]
    order_id: int
    transaksi_id: Optional[str]
    status_code: Optional[str] # Dibuat opsional karena mungkin tidak ada di callback sederhana
    transaction_status: str
    gross_amount: float
    payment_type: str
    qr_code_url: Optional[str]
    transaction_time: Optional[datetime]
    settlement_time: Optional[datetime] = Field(None, alias="settlement_time")
    signature_key: Optional[str]

class FcmTokenCreate(BaseModel):
    token: str