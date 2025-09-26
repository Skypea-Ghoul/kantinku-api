from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from pydantic import Field

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
    gambar: Optional[str] = None

class ProductCreate(BaseModel):
    nama_produk: str
    harga: int
    kategori_id: int
    gambar: Optional[str] = None

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

# Orders
class Order(BaseModel):
    id: Optional[int]
    user_id: int
    status: str
    total_harga: float
    tanggal_pesanan: Optional[str] = Field(None, description="Waktu pesanan dibuat dalam format string") 

# OrderItems
class OrderItem(BaseModel):
    id: Optional[int]
    order_id: int
    product_id: int
    jumlah: int
    harga_unit: float
    subtotal: float

# Payments
class Payment(BaseModel):
    id: Optional[int]
    order_id: int
    transaksi_id_midtrans: Optional[str]
    metode_pembayaran: str
    jumlah_pembayaran: float
    tanggal_pembayaran: Optional[datetime]
    status_pembayaran: str
    nomor_va: Optional[str]
    qr_code_url: Optional[str]
    waktu_penyelesaian: Optional[datetime]
