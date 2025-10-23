from .config import supabase
from .models import *
from supabase import Client
from typing import List, Dict, Any
import base64
import math

# Generic helper

# CRUD operations for users
def fetch(table: str, filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    try:
        query = supabase.table(table).select("*")  # eksplisit
        if filters:
            for k, v in filters.items():
                query = query.eq(k, v)
        result = query.execute()
        return result.data or []
    except Exception as e:
        print(f"Error saat fetch: {e}")
        return []
    
def hitung_harga_jual(harga_awal: int, biaya_tetap: int, fee_persen: float, ppn_persen: float) -> int:
    """Menghitung harga jual akhir dengan memperhitungkan biaya tetap, fee transaksi, dan PPN atas fee."""
    fee_decimal = fee_persen / 100
    ppn_decimal = ppn_persen / 100
    
    # Total persentase biaya = fee + (PPN * fee)
    total_persentase_biaya = fee_decimal + (fee_decimal * ppn_decimal)
    
    if total_persentase_biaya >= 1:
        # Menghindari pembagian dengan nol atau angka negatif
        raise ValueError("Total persentase biaya tidak valid.")

    harga_jual_kotor = (harga_awal + biaya_tetap) / (1 - total_persentase_biaya)
    
    # Bulatkan ke atas (ceiling) untuk memastikan tidak ada kerugian
    return math.ceil(harga_jual_kotor)

def insert(user: UserCreate) -> UserOut:
    try:
        data = supabase.table("users").insert(user.dict()).execute()
        return UserOut(**data.data[0])
    except Exception as e:
        print("Insert error:", e)
        return None


def update(table: str, id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    result = supabase.table(table).update(payload).eq('id', id).execute()
    data = result.data
    return data[0] if isinstance(data, list) and data else None


def delete(table: str, id: int) -> Dict[str, Any]:
    result = supabase.table(table).delete().eq('id', id).execute()
    data = result.data
    return data[0] if isinstance(data, list) and data else None


# CRUD operations for products

def fetch_products(filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    try:
        query = supabase.table("products").select("*")
        if filters:
            for k, v in filters.items():
                query = query.eq(k, v)
        
        result = query.execute()
        
        # Check if data exists
        if not result.data:
            return []
        
        products_list = result.data
        
        # Tidak perlu konversi gambar, karena sudah varchar base64
        return products_list
    except Exception as e:
        print(f"Error fetching products: {e}")
        return []
    
def insert_product(product: ProductCreate, user_id: int) -> ProductOut:
    try:
        # Pydantic's .model_dump() is a good practice for modern versions
        product_dict = product.model_dump()
        
        # We're no longer decoding here. The client sends the Base64 string directly
        # The Supabase 'BYTEA' column will store this Base64 representation.
        data = supabase.table("products").insert(product_dict).execute()
        
        if not data.data:
            raise Exception("Failed to insert product. Supabase returned no data.")
            
        product_data = data.data[0]
        product_id = product_data['id']
        
        supabase.table("product_users").insert({'user_id': user_id, 'product_id': product_id}).execute()
        
        return ProductOut(**product_data)
    except Exception as e:
        print(f"Insert product error: {e}")
        raise e

# Fungsi untuk memeriksa kepemilikan produk
def is_product_owner(user_id: int, product_id: int) -> bool:
    try:
        result = supabase.table("product_users").select("*").eq('user_id', user_id).eq('product_id', product_id).execute()
        return len(result.data) > 0
    except Exception as e:
        print(f"Error checking product ownership: {e}")
        return False


# CRUD operations for categories
def fetch_categories(filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    try:
        query = supabase.table("categories").select("*")
        if filters:
            for k, v in filters.items():
                query = query.eq(k, v)
        result = query.execute()
        return result.data or []
    except Exception as e:
        print(f"Error saat fetch categories: {e}")
        return []
    
def insert_category(category: CategoryCreate) -> CategoryOut:
    try:
        data = supabase.table("categories").insert(category.dict()).execute()
        return CategoryOut(**data.data[0])
    except Exception as e:
        print("Insert category error:", e)
        return None

# CRUD operations for carts
def fetch_carts(filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    try:
        query = supabase.table("cart_items").select("*")
        if filters:
            for k, v in filters.items():
                query = query.eq(k, v)
        result = query.execute()
        return result.data or []
    except Exception as e:
        print(f"Error saat fetch carts: {e}")
        return []
    
# CRUD operations for orders
def fetch_orders(filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    try:
        query = supabase.table("orders").select("*")
        if filters:
            for k, v in filters.items():
                query = query.eq(k, v)
        result = query.execute()
        return result.data or []
    except Exception as e:
        print(f"Error saat fetch orders: {e}")
        return []