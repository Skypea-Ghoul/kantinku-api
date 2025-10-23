from fastapi import APIRouter, Depends, HTTPException, status, WebSocket
from typing import List, Dict, Any
from ..models import Order, OrderItem, Order as OrderModel, UserOut, ProductSalesSummary
from ..crud import fetch_orders, is_product_owner
from .dependencies import get_current_user
from ..config import supabase
from datetime import datetime
from pydantic import BaseModel
from .websockets import manager
import json
# ✅ Import hanya untuk notifikasi pesanan siap (bukan pesanan baru)
from ..services.notification_service import send_order_ready_notification


class SalesSummary(BaseModel):
    tanggal: str
    total_penjualan: float

router = APIRouter(prefix="/orders", tags=["Orders"])

@router.get("/", response_model=List[Order])
async def get_orders(current_user=Depends(get_current_user)):
    """Ambil semua order milik user yang login."""
    orders = fetch_orders({"user_id": current_user.id})
    return orders

@router.get("/staff/inbox", response_model=List[Order])
async def fetch_staff_order_inbox(include_items: bool = False, current_user: UserOut = Depends(get_current_user)):
    """
    Mengambil semua pesanan (Orders) yang produknya dimiliki oleh Staff yang login
    dan memiliki status yang relevan.
    """
    if current_user.role != "staff":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses ditolak. Hanya untuk staff.")

    inbox_orders_query = supabase.rpc(
        "get_staff_inbox_orders", {"p_staff_id": current_user.id}
    ).execute()
   
    if not inbox_orders_query.data:
        return []

    orders_list = inbox_orders_query.data

    if include_items:
        order_ids = [order['id'] for order in orders_list]
        
        staff_products_query = supabase.table("product_users").select("product_id").eq("user_id", current_user.id).execute()
        staff_product_ids = [product['product_id'] for product in staff_products_query.data] 

        if not staff_product_ids:
            for order in orders_list:
                order['items'] = []
            return [Order(**order) for order in orders_list]

        all_items_query = supabase.table("order_items").select("*").in_("order_id", order_ids).in_("product_id", staff_product_ids).execute()
        
        items_by_order_id = {}
        for item in all_items_query.data:
            order_id = item['order_id']
            if order_id not in items_by_order_id:
                items_by_order_id[order_id] = []
            items_by_order_id[order_id].append(item)
            
        for order in orders_list:
            order['items'] = items_by_order_id.get(order['id'], [])

    return [Order(**order) for order in orders_list]

@router.put("/{order_id}/status", response_model=Order)
async def update_order_status(order_id: int, status_update: dict, current_user: UserOut = Depends(get_current_user)):
    if current_user.role != "staff":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hanya staff yang bisa mengubah status.")

    new_status = status_update.get("status")
    if not new_status:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Status baru harus disediakan.")

    updated_order = supabase.table("orders").update({"status": new_status}).eq("id", order_id).execute()

    if not updated_order.data:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan atau gagal diupdate.")

    return updated_order.data[0]

@router.get("/staff/sales-summary", response_model=List[SalesSummary])
def get_staff_sales_summary(current_user: UserOut = Depends(get_current_user)):
    """
    Mengambil rekap penjualan harian untuk staff yang login.
    Hanya menghitung dari pesanan yang berstatus 'completed'.
    """
    if current_user.role != "staff":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Hanya untuk staff."
        )
    
    sales_data = supabase.rpc(
        "get_staff_daily_sales", {"p_staff_id": current_user.id}
    ).execute()

    return sales_data.data or []

@router.get("/staff/product-summary", response_model=List[ProductSalesSummary], tags=["Staff Actions"])
def get_staff_product_summary(current_user: UserOut = Depends(get_current_user)):
    """
    Mengambil rekap penjualan per produk untuk staff yang login.
    Hanya menghitung dari pesanan yang berstatus 'completed'.
    """
    if current_user.role != "staff":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,  
            detail="Akses ditolak. Hanya untuk staff."
        )
    
    summary_data = supabase.rpc(
        "get_staff_product_summary", {"p_staff_id": current_user.id}
    ).execute()

    return summary_data.data or []

@router.get("/{order_id}", response_model=Order)
async def get_order_by_id(order_id: int, current_user=Depends(get_current_user)):
    """Ambil detail order milik user yang login."""
    order = supabase.table("orders").select("*").eq("id", order_id).single().execute().data
    if not order or order["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan atau bukan milik Anda")
    return order

@router.post("/", response_model=Order)
async def create_order(current_user=Depends(get_current_user)):
    """
    Membuat order baru dari semua item di keranjang user.
    
    CATATAN: Notifikasi ke staff akan dikirim otomatis lewat payment callback 
    setelah pembayaran berhasil (bukan di sini).
    """
    cart_items = supabase.table("cart_items").select("*").eq("user_id", current_user.id).execute().data
    
    if not cart_items:
        raise HTTPException(status_code=400, detail="Keranjang kosong")
    
    total_harga = 0
    for item in cart_items:
        product = supabase.table("products").select("harga").eq("id", item["product_id"]).execute().data
        harga = product[0]["harga"] if isinstance(product, list) and product else product["harga"]
        total_harga += item["jumlah"] * harga
    
    status_order = "pending"
    current_time_str = datetime.now().isoformat()
    
    order_data = {
        "user_id": current_user.id,
        "status": status_order,
        "total_harga": total_harga,
        "tanggal_pesanan": current_time_str,
    }
    
    order_insert = supabase.table("orders").insert(order_data).execute().data
    
    if not order_insert or not isinstance(order_insert, list) or not order_insert[0]:
        raise HTTPException(status_code=500, detail="Gagal insert order")
    
    order = order_insert[0]
    
    order_items_to_create = []
    for item in cart_items:
        product = supabase.table("products").select("harga").eq("id", item["product_id"]).single().execute().data
        order_items_to_create.append({
            "order_id": order['id'],
            "product_id": item["product_id"],
            "jumlah": item["jumlah"],
            "harga_unit": product['harga'],
            "subtotal": item["jumlah"] * product['harga']
        })

    supabase.table("order_items").insert(order_items_to_create).execute()
    supabase.table("cart_items").delete().eq("user_id", current_user.id).execute()
   
    # ✅ NOTIFIKASI PESANAN BARU DIKIRIM DI PAYMENT CALLBACK (bukan di sini)
    # Lihat file payments.py -> midtrans_callback()
    
    return Order(**order)

@router.put("/{order_id}", response_model=Order)
async def update_order(order_id: int, order_update: Order, current_user=Depends(get_current_user)):
    """Update status atau total_harga order milik user yang login."""
    order = supabase.table("orders").select("*").eq("id", order_id).single().execute().data
    if not order or order["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan atau bukan milik Anda")
    
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
async def delete_order(order_id: int, current_user=Depends(get_current_user)):
    """Hapus order milik user yang login (beserta order_items-nya)."""
    order = supabase.table("orders").select("*").eq("id", order_id).single().execute().data
    if not order or order["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan atau bukan milik Anda")
    
    supabase.table("order_items").delete().eq("order_id", order_id).execute()
    supabase.table("orders").delete().eq("id", order_id).execute()
    return {"message": f"Order {order_id} berhasil dihapus"}

@router.get("/items/me", response_model=List[OrderItem])
async def get_my_order_items(current_user=Depends(get_current_user)):
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
async def get_order_items(order_id: int, current_user=Depends(get_current_user)):
    """
    Ambil semua item pada sebuah order.
    - Customer hanya bisa melihat item dari order miliknya.
    - Staff bisa melihat item dari order jika order tersebut mengandung produk miliknya.
    """
    order_query = supabase.table("orders").select("*").eq("id", order_id).execute()
    if not order_query.data:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan")

    order = order_query.data[0]

    if current_user.role == "customer":
        if order["user_id"] != current_user.id:
            raise HTTPException(status_code=403, detail="Anda tidak memiliki akses ke pesanan ini.")
    elif current_user.role == "staff":
        staff_products_query = supabase.table("product_users").select("product_id").eq("user_id", current_user.id).execute()
        staff_product_ids = [p['product_id'] for p in staff_products_query.data]

        if not staff_product_ids:
             raise HTTPException(status_code=403, detail="Anda tidak memiliki produk untuk melihat pesanan ini.")

        items_in_order_query = supabase.table("order_items").select("id").eq("order_id", order_id).in_("product_id", staff_product_ids).execute()
        
        if not items_in_order_query.data:
            raise HTTPException(status_code=403, detail="Anda tidak memiliki akses ke item pesanan ini.")
    else:
        raise HTTPException(status_code=403, detail="Akses ditolak.")

    items = supabase.table("order_items").select("*").eq("order_id", order_id).execute().data
    return items

@router.put("/{order_id}/update-overall-status", response_model=Order, tags=["Staff Actions"])
async def update_overall_order_status(
    order_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """
    Mengecek status semua item dalam sebuah pesanan dan memperbarui
    status pesanan utama (Order) sesuai dengan logika yang ditentukan.
    Hanya bisa di-trigger oleh staff.
    """
    if current_user.role != "staff":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hanya staff yang bisa melakukan aksi ini.")

    order_query = supabase.table("orders").select("*").eq("id", order_id).single().execute()
    if not order_query.data:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan")

    db_order = order_query.data

    order_items_query = supabase.table("order_items").select("status").eq("order_id", order_id).execute()
    order_items = order_items_query.data
    if not order_items:
        return Order(**db_order)

    item_statuses = {item['status'] for item in order_items}
    
    new_order_status = db_order['status']

    if all(s == 'completed' for s in item_statuses):
        new_order_status = 'completed'
    elif all(s in ['ready_for_pickup', 'completed'] for s in item_statuses):
        new_order_status = 'ready_for_pickup'
    elif all(s in ['cooking', 'ready_for_pickup', 'completed'] for s in item_statuses):
        new_order_status = 'cooking'

    if db_order['status'] != new_order_status:
        updated_order_query = supabase.table("orders").update({"status": new_order_status}).eq("id", order_id).execute()
        updated_order_data = updated_order_query.data[0]

        customer_id = updated_order_data['user_id']
        notification_payload = json.dumps({
            "type": "order_status_update", 
            "order_id": order_id, 
            "new_status": new_order_status
        })
        await manager.broadcast_to_user(customer_id, notification_payload)
        
        return Order(**updated_order_data)

    return Order(**db_order)

@router.put("/items/{item_id}/status", response_model=OrderItem, tags=["Staff Actions"])
async def update_order_item_status(
    item_id: int, 
    status_update: dict, 
    current_user: UserOut = Depends(get_current_user)
):
    """
    Mengubah status satu item pesanan (OrderItem).
    Hanya bisa dilakukan oleh staff yang memiliki produk tersebut.
    
    ✅ Mengirim notifikasi push ke customer jika SEMUA item sudah 'completed'
    """
    if current_user.role != "staff":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hanya staff yang bisa mengubah status item.")

    item_query = supabase.table("order_items").select("*").eq("id", item_id).single().execute()
    if not item_query.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item pesanan tidak ditemukan.")
    
    order_item = item_query.data
    order_id = order_item['order_id']
    product_id = order_item['product_id']

    if not is_product_owner(current_user.id, product_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Anda tidak memiliki hak untuk mengubah status item ini.")

    new_status = status_update.get("status")
    if not new_status:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Status baru harus disediakan dalam body request, contoh: {'status': 'cooking'}")

    updated_item_query = supabase.table("order_items").update({"status": new_status}).eq("id", item_id).execute()

    if not updated_item_query.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Gagal memperbarui status item.")

    updated_item_data = updated_item_query.data[0]

    # --- WEBSOCKET NOTIFICATION ---
    order_query = supabase.table("orders").select("user_id, status").eq("id", order_id).single().execute()
    if order_query.data:
        customer_id = order_query.data['user_id']
        notification_payload = json.dumps({
            "type": "item_status_update",
            "item_id": item_id,
            "order_id": order_id,
            "new_status": new_status
        })
        await manager.broadcast_to_user(customer_id, notification_payload)
        
        # --- PUSH NOTIFICATION (Pesanan Siap) ---
        if new_status == 'completed' and order_query.data['status'] != 'completed':
            all_items_query = supabase.table("order_items").select("status").eq("order_id", order_id).execute()
            if all_items_query.data:
                all_statuses = [item['status'] for item in all_items_query.data]
                
                if all(s == 'completed' for s in all_statuses):
                    supabase.table("orders").update({"status": "completed"}).eq("id", order_id).execute()
                    
                    print(f"✅ Semua item untuk order {order_id} completed. Mengirim notifikasi ke user {customer_id}.")
                    send_order_ready_notification(user_id=customer_id, order_id=order_id)
    
    return OrderItem(**updated_item_data)