import os
import midtransclient
from fastapi import APIRouter, HTTPException, Depends, Request
from ..config import supabase
from datetime import datetime
from .dependencies import get_current_user
from typing import List, Optional
from ..crud import hitung_harga_jual
from pydantic import BaseModel
from ..models import Payment
import json
from typing import Set 
import uuid
from .websockets import manager
from ..services.notification_service import send_new_order_notification_to_staff  # ✅ TAMBAH INI

router = APIRouter(prefix="/payments", tags=["Payments"])

class SnapTokenRequest(BaseModel):
    user_id: int
    cart_ids: List[int]

@router.post("/snap-token")
def get_snap_token(data: SnapTokenRequest):
    user_id = data.user_id
    cart_ids = data.cart_ids

    user = supabase.table("users").select("nama_pengguna, nomor_telepon").eq("id", user_id).single().execute().data
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    cart_items = supabase.table("cart_items").select("*").in_("id", cart_ids).execute().data
    if not cart_items:
        raise HTTPException(status_code=404, detail="Cart item tidak ditemukan")

    fee_qris = 0.7
    biaya_tetap = 500
    ppn_persen = 11

    item_details = []
    subtotal_harga_awal = 0
    for cart_item in cart_items:
        product = supabase.table("products").select("nama_produk,harga").eq("id", cart_item["product_id"]).single().execute().data
        harga_awal = int(product["harga"])
        item_details.append({
            "id": str(cart_item["product_id"]),
            "price": harga_awal,
            "quantity": int(cart_item["jumlah"]),
            "name": product["nama_produk"]
        })
        subtotal_harga_awal += harga_awal * int(cart_item["jumlah"])
    
    harga_jual_akhir = hitung_harga_jual(subtotal_harga_awal, biaya_tetap, fee_qris, ppn_persen)

    biaya_layanan = harga_jual_akhir - subtotal_harga_awal
    if biaya_layanan > 0:
        item_details.append({"id": "SERVICE_FEE", "price": biaya_layanan, "quantity": 1, "name": "Biaya Layanan & Pajak"})

    order_data = {
        "user_id": user_id,
        "status": "pending",
        "total_harga": harga_jual_akhir,
        "tanggal_pesanan": datetime.now().isoformat(),
    }
    order_insert_res = supabase.table("orders").insert(order_data).execute()
    if not order_insert_res.data:
        raise HTTPException(status_code=500, detail="Gagal membuat order di database.")
    
    new_order = order_insert_res.data[0]
    order_id = new_order['id']

    unique_midtrans_order_id = f"{order_id}-{uuid.uuid4().hex[:6]}"

    order_items_to_create = []
    for cart_item in cart_items:
        product = supabase.table("products").select("harga").eq("id", cart_item["product_id"]).single().execute().data
        order_items_to_create.append({
            "order_id": order_id,
            "product_id": cart_item["product_id"],
            "jumlah": cart_item["jumlah"],
            "harga_unit": product['harga'],
            "subtotal": cart_item["jumlah"] * product['harga']
        })
    supabase.table("order_items").insert(order_items_to_create).execute()

    initial_payment_data = {
        "order_id": order_id,
        "transaksi_id": f"pending-{order_id}",
        "transaction_status": "pending",
        "gross_amount": harga_jual_akhir,
        "payment_type": "qris"
    }
    supabase.table("payments").insert(initial_payment_data).execute()

    snap = midtransclient.Snap(
        is_production=False,
        server_key=os.getenv("MIDTRANS_SERVER_KEY")
    )

    param = {
        "transaction_details": {
            "order_id": unique_midtrans_order_id,
            "gross_amount": harga_jual_akhir
        },
        "item_details": item_details,
        "enabled_payments": ["gopay"],
        "customer_details": {
            "first_name": user["nama_pengguna"],
            "phone": user["nomor_telepon"]
        }
    }

    transaction = snap.create_transaction(param)
    snap_token = transaction.get('token')
    redirect_url = transaction.get('redirect_url')

    if redirect_url:
        supabase.table("orders").update({"snap_redirect_url": redirect_url}).eq("id", order_id).execute()

    return {
        "snap_token": snap_token,
        "redirect_url": redirect_url
    }

@router.post("/callback", include_in_schema=False)
async def midtrans_callback(request: Request):
    body = await request.json()
    print("MIDTRANS CALLBACK BODY:", body)

    order_id_raw = body.get("order_id")
    transaction_status = body.get("transaction_status")

    if not order_id_raw or not transaction_status:
        raise HTTPException(status_code=400, detail="Data callback wajib hilang")
    
    try:
        order_id_int = int(order_id_raw.split('-')[0])
    except Exception:
        raise HTTPException(status_code=400, detail="Format order_id dari callback tidak valid")

    if transaction_status in ["settlement", "capture"]:
        final_order_status = "paid"
    elif transaction_status in ["pending", "authorize"]:
        final_order_status = "pending"
    else:
        final_order_status = "cancelled"

    payment_data = {
        "order_id": order_id_int,
        "transaksi_id": body.get("transaction_id"),
        "status_code": body.get("status_code"),
        "transaction_status": transaction_status,
        "gross_amount": float(body.get("gross_amount")),
        "payment_type": body.get("payment_type"),
        "transaction_time": body.get("transaction_time"),
        "settlement_time": body.get("settlement_time"),
    }
    supabase.table("payments").update(payment_data).eq("order_id", order_id_int).execute()

    if final_order_status == "paid":
        current_order_query = supabase.table("orders").select("status").eq("id", order_id_int).single().execute()
        # Jika order tidak ditemukan atau statusnya sudah 'paid', hentikan proses.
        if not current_order_query.data or current_order_query.data['status'] == 'paid':
            print(f"Order #{order_id_int} sudah diproses sebelumnya. Melewati notifikasi duplikat.")
            return {"message": "Callback for an already processed order was ignored."}

        supabase.table("orders").update({"status": "paid"}).eq("id", order_id_int).execute()
        supabase.table("order_items").update({"status": "paid"}).eq("order_id", order_id_int).execute()

        # --- BLOK NOTIFIKASI (WEBSOCKET + PUSH NOTIFICATION) ---
        order_items_query = supabase.table("order_items").select("product_id").eq("order_id", order_id_int).execute()
        
        if order_items_query.data:
            product_ids_in_order = {item['product_id'] for item in order_items_query.data}

            staff_query = supabase.table("product_users").select("user_id").in_("product_id", list(product_ids_in_order)).execute()
            
            if staff_query.data:
                # ✅ Konversi set ke list untuk notifikasi
                staff_ids_set: Set[int] = {item['user_id'] for item in staff_query.data}
                staff_ids_list = list(staff_ids_set)
                
                print(f"📢 Mengirim notifikasi pesanan #{order_id_int} ke staff ID: {staff_ids_list}")
                
                # ✅ 1. KIRIM PUSH NOTIFICATION FCM
                send_new_order_notification_to_staff(
                    staff_ids=staff_ids_list, 
                    order_id=order_id_int
                )
                
                # ✅ 2. KIRIM WEBSOCKET NOTIFICATION
                notification_payload = json.dumps({
                    "type": "new_order", 
                    "order_id": order_id_int, 
                    "message": f"🔔 Pesanan baru #{order_id_int} telah masuk!"
                })
                
                for staff_id in staff_ids_list:
                    await manager.broadcast_to_user(staff_id, notification_payload)
        # --- AKHIR BLOK NOTIFIKASI ---

        # Hapus keranjang
        order_query = supabase.table("orders").select("user_id").eq("id", order_id_int).single().execute()
        if order_query.data:
            user_id = order_query.data["user_id"]
            supabase.table("cart_items").delete().eq("user_id", user_id).execute()
            print(f"Cart items for user {user_id} deleted successfully.")
    
    return {
        "message": "Callback processed",
        "order_id": order_id_raw,
        "status": transaction_status
    }

@router.get("/by-order/{order_id}", response_model=List[Payment])
def get_payment_details(order_id: int, current_user=Depends(get_current_user)):
    """
    Mengambil detail pembayaran (Payment) berdasarkan ID Pesanan (Order ID).
    """
    order_query = supabase.table("orders").select("user_id").eq("id", order_id).single().execute()
    
    if not order_query.data:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan.")
    
    if order_query.data["user_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Akses ditolak.")
        
    payment_details_query = supabase.table("payments").select("*").eq("order_id", order_id).execute()
    
    if not payment_details_query.data:
        return [] 
        
    return [Payment(**p) for p in payment_details_query.data]