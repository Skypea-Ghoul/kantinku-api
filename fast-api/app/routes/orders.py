from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from ..models import Order, OrderItem, Order as OrderModel
from ..crud import fetch_orders
from .dependencies import get_current_user
from ..config import supabase

router = APIRouter(prefix="/orders", tags=["Orders"])

@router.get("/", response_model=List[Order])
def get_orders(current_user=Depends(get_current_user)):
    """Ambil semua order milik user yang login."""
    orders = fetch_orders({"user_id": current_user.id})
    return orders

@router.get("/{order_id}", response_model=Order)
def get_order_by_id(order_id: int, current_user=Depends(get_current_user)):
    """Ambil detail order milik user yang login."""
    order = supabase.table("orders").select("*").eq("id", order_id).single().execute().data
    if not order or order["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan atau bukan milik Anda")
    return order

@router.post("/", response_model=Order)
def create_order(current_user=Depends(get_current_user)):
    """
    Membuat order baru dari semua item di keranjang user.
    Semua item di keranjang akan dipindahkan ke order_items.
    """
    cart_items = supabase.table("cart_items").select("*").eq("user_id", current_user.id).execute().data
    if not cart_items:
        raise HTTPException(status_code=400, detail="Keranjang kosong")
    total_harga = 0
    for item in cart_items:
        product = supabase.table("products").select("harga").eq("id", item["product_id"]).execute().data
        harga = product[0]["harga"] if isinstance(product, list) and product else product["harga"]
        total_harga += item["jumlah"] * harga
    # Pastikan status sesuai constraint
    allowed_status = ["pending", "paid", "cancelled"]
    status_order = "pending"
    if status_order not in allowed_status:
        raise HTTPException(status_code=400, detail=f"Status order harus salah satu dari: {allowed_status}")
    order_data = {
        "user_id": current_user.id,
        "status": status_order,
        "total_harga": total_harga
    }
    order_insert = supabase.table("orders").insert(order_data).execute().data
    if not order_insert or not isinstance(order_insert, list) or not order_insert[0]:
        raise HTTPException(status_code=500, detail="Gagal insert order")
    order = order_insert[0]
    # Buat order_items
    for item in cart_items:
        product = supabase.table("products").select("harga").eq("id", item["product_id"]).execute().data
        harga = product[0]["harga"] if isinstance(product, list) and product else product["harga"]
        supabase.table("order_items").insert({
            "order_id": order["id"],
            "product_id": item["product_id"],
            "jumlah": item["jumlah"],
            "harga_unit": harga,
            "subtotal": item["jumlah"] * harga
        }).execute()
    # Hapus keranjang user
    supabase.table("cart_items").delete().eq("user_id", current_user.id).execute()
    return order

@router.put("/{order_id}", response_model=Order)
def update_order(order_id: int, order_update: Order, current_user=Depends(get_current_user)):
    """Update status atau total_harga order milik user yang login."""
    order = supabase.table("orders").select("*").eq("id", order_id).single().execute().data
    if not order or order["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan atau bukan milik Anda")
    # Hanya boleh update status dan total_harga (atau field lain sesuai kebutuhan)
    update_data = {}
    if order_update.status:
        update_data["status"] = order_update.status
    if order_update.total_harga:
        update_data["total_harga"] = order_update.total_harga
    if not update_data:
        raise HTTPException(status_code=400, detail="Tidak ada data yang diupdate")
    updated = supabase.table("orders").update(update_data).eq("id", order_id).execute().data[0]
    return updated

@router.delete("/{order_id}")
def delete_order(order_id: int, current_user=Depends(get_current_user)):
    """Hapus order milik user yang login (beserta order_items-nya)."""
    order = supabase.table("orders").select("*").eq("id", order_id).single().execute().data
    if not order or order["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan atau bukan milik Anda")
    # Hapus order_items terlebih dahulu
    supabase.table("order_items").delete().eq("order_id", order_id).execute()
    # Hapus order
    supabase.table("orders").delete().eq("id", order_id).execute()
    return {"message": f"Order {order_id} berhasil dihapus"}

@router.get("/items/me", response_model=List[OrderItem])
def get_my_order_items(current_user=Depends(get_current_user)):
    """
    Ambil semua order_items milik customer yang login.
    Staff hanya bisa melihat order_items dari produk yang memang dipesan customer.
    """
    if current_user.role == "customer":
        orders = supabase.table("orders").select("id").eq("user_id", current_user.id).execute().data
        order_ids = [order["id"] for order in orders]
        if not order_ids:
            return []
        items = supabase.table("order_items").select("*").in_("order_id", order_ids).execute().data
        return items
    elif current_user.role == "staff":
        product_users = supabase.table("product_users").select("product_id").eq("user_id", current_user.id).execute().data
        product_ids = [pu["product_id"] for pu in product_users]
        if not product_ids:
            return []
        items = supabase.table("order_items").select("*").in_("product_id", product_ids).execute().data
        return items
    else:
        raise HTTPException(status_code=403, detail="Role tidak diizinkan untuk melihat order items.")

@router.get("/{order_id}/items", response_model=List[OrderItem])
def get_order_items(order_id: int, current_user=Depends(get_current_user)):
    """Ambil semua item pada order milik user yang login."""
    order = supabase.table("orders").select("*").eq("id", order_id).single().execute().data
    if not order or order["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan atau bukan milik Anda")
    items = supabase.table("order_items").select("*").eq("order_id", order_id).execute().data
    return items