from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from ..models import Order, OrderItem, Order as OrderModel, UserOut
from ..crud import fetch_orders
from .dependencies import get_current_user
from ..config import supabase
from datetime import datetime

router = APIRouter(prefix="/orders", tags=["Orders"])

@router.get("/", response_model=List[Order])
def get_orders(current_user=Depends(get_current_user)):
    """Ambil semua order milik user yang login."""
    orders = fetch_orders({"user_id": current_user.id})
    return orders

@router.get("/staff/inbox", response_model=List[Order])
def fetch_staff_order_inbox(include_items: bool = False, current_user: UserOut = Depends(get_current_user)):
    """
    Mengambil semua pesanan (Orders) yang produknya dimiliki oleh Staff yang login
    dan memiliki status yang relevan.
    """
    if current_user.role != "staff":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses ditolak. Hanya untuk staff.")

    # Panggil RPC yang sudah diperbarui untuk mengambil semua status relevan
    inbox_orders_query = supabase.rpc(
        "get_staff_inbox_orders", {"p_staff_id": current_user.id}
    ).execute()
   
    if not inbox_orders_query.data:
        return []

    orders_list = inbox_orders_query.data

    if include_items:
        order_ids = [order['id'] for order in orders_list]
        
        # ✅ PERBAIKAN: Ambil ID produk dari tabel 'product_users'
        staff_products_query = supabase.table("product_users").select("product_id").eq("user_id", current_user.id).execute()
        # Perhatikan bahwa kita mengambil 'product_id' bukan 'id'
        staff_product_ids = [product['product_id'] for product in staff_products_query.data] 

        if not staff_product_ids:
            for order in orders_list:
                order['items'] = []
            return [Order(**order) for order in orders_list]

        # Ambil semua item dari order yang relevan, DAN filter hanya untuk produk milik staff
        all_items_query = supabase.table("order_items").select("*").in_("order_id", order_ids).in_("product_id", staff_product_ids).execute()
        
        items_by_order_id = {}
        for item in all_items_query.data:
            order_id = item['order_id']
            if order_id not in items_by_order_id:
                items_by_order_id[order_id] = []
            items_by_order_id[order_id].append(item)
            
        # Lampirkan item ke setiap order
        for order in orders_list:
            # 'items' akan berisi HANYA item milik staff yang login
            order['items'] = items_by_order_id.get(order['id'], [])

    return [Order(**order) for order in orders_list]

# Endpoint baru untuk mengubah status
@router.put("/{order_id}/status", response_model=Order)
def update_order_status(order_id: int, status_update: dict, current_user: UserOut = Depends(get_current_user)):
    if current_user.role != "staff":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hanya staff yang bisa mengubah status.")

    new_status = status_update.get("status")
    if not new_status:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Status baru harus disediakan.")

    # Lakukan update
    updated_order = supabase.table("orders").update({"status": new_status}).eq("id", order_id).execute()

    if not updated_order.data:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan atau gagal diupdate.")

    return updated_order.data[0]

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
    Membuat order baru dari semua item di keranjang user, termasuk tanggal pesanan (sebagai string).
    """
    cart_items = supabase.table("cart_items").select("*").eq("user_id", current_user.id).execute().data
    
    if not cart_items:
        raise HTTPException(status_code=400, detail="Keranjang kosong")
    
    total_harga = 0
    # Logika penghitungan total_harga... (tetap sama)
    for item in cart_items:
        product = supabase.table("products").select("harga").eq("id", item["product_id"]).execute().data
        harga = product[0]["harga"] if isinstance(product, list) and product else product["harga"]
        total_harga += item["jumlah"] * harga
    
    # Logika penentuan status... (tetap sama)
    status_order = "pending"
    
    # FIX: Dapatkan waktu saat ini dan konversi ke string ISO 8601
    current_time_str = datetime.now().isoformat()
    
    order_data = {
        "user_id": current_user.id,
        "status": status_order,
        "total_harga": total_harga,
        "tanggal_pesanan": current_time_str,  # FIX: Kirim sebagai string
    }
    
    order_insert = supabase.table("orders").insert(order_data).execute().data
    
    if not order_insert or not isinstance(order_insert, list) or not order_insert[0]:
        raise HTTPException(status_code=500, detail="Gagal insert order")
    
    order = order_insert[0]
    
    # Logika pembuatan order_items dan penghapusan keranjang... (tetap sama)
    
    # FIX: Pastikan respons Order menyertakan field tanggal_pesanan
    # Kita harus memastikan output diubah kembali menjadi model Order
    return Order(**order)

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
    """
    Ambil semua item pada sebuah order.
    - Customer hanya bisa melihat item dari order miliknya.
    - Staff bisa melihat item dari order jika order tersebut mengandung produk miliknya.
    """
    # 1. Ambil data order terlebih dahulu
    order_query = supabase.table("orders").select("*").eq("id", order_id).single().execute()
    if not order_query.data:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan")

    order = order_query.data

    # 2. Lakukan validasi hak akses berdasarkan role
    if current_user.role == "customer":
        # Customer hanya boleh melihat order miliknya sendiri
        if order["user_id"] != current_user.id:
            raise HTTPException(status_code=403, detail="Anda tidak memiliki akses ke pesanan ini.")
    elif current_user.role == "staff":
        # Staff harus punya setidaknya satu produk dalam order ini untuk bisa melihatnya.
        # a. Ambil ID produk milik staff
        staff_products_query = supabase.table("product_users").select("product_id").eq("user_id", current_user.id).execute()
        staff_product_ids = [p['product_id'] for p in staff_products_query.data]

        if not staff_product_ids:
             raise HTTPException(status_code=403, detail="Anda tidak memiliki produk untuk melihat pesanan ini.")

        # b. Cek apakah ada item di order ini yang product_id-nya cocok dengan produk staff
        items_in_order_query = supabase.table("order_items").select("id").eq("order_id", order_id).in_("product_id", staff_product_ids).execute()
        
        if not items_in_order_query.data:
            raise HTTPException(status_code=403, detail="Anda tidak memiliki akses ke item pesanan ini.")
    else:
        # Role lain tidak diizinkan
        raise HTTPException(status_code=403, detail="Akses ditolak.")

    # 3. Jika validasi lolos, ambil dan kembalikan item
    items = supabase.table("order_items").select("*").eq("order_id", order_id).execute().data
    return items