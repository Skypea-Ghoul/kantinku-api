import os
import midtransclient
from fastapi import APIRouter, HTTPException, Depends, Request
from ..config import supabase
from datetime import datetime
from .dependencies import get_current_user
from typing import List
from ..crud import hitung_harga_jual
from pydantic import BaseModel

router = APIRouter(prefix="/payments", tags=["Payments"])

class SnapTokenRequest(BaseModel):
    user_id: int
    cart_ids: List[int]

@router.post("/snap-token")
def get_snap_token(data: SnapTokenRequest):
    user_id = data.user_id
    cart_ids = data.cart_ids

    # Ambil user
    user = supabase.table("users").select("*").eq("id", user_id).single().execute().data
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    # Ambil semua cart_items berdasarkan cart_ids
    cart_items = supabase.table("cart_items").select("*").in_("id", cart_ids).execute().data
    if not cart_items:
        raise HTTPException(status_code=404, detail="Cart item tidak ditemukan")

    # Fee QRIS dan target untung (bisa diambil dari config/database jika dinamis)
    fee_qris = 0.7  # persen
    target_untung = 500  # rupiah

    item_details = []
    total_harga = 0
    for item in cart_items:
        product = supabase.table("products").select("nama_produk,harga").eq("id", item["product_id"]).single().execute().data
        harga_awal = int(product["harga"])
        harga_jual, markup = hitung_harga_jual(harga_awal, target_untung, fee_qris)
        item_details.append({
            "id": str(item["product_id"]),
            "price": harga_jual,
            "quantity": int(item["jumlah"]),
            "name": product["nama_produk"]
        })
        total_harga += harga_jual * int(item["jumlah"])

    snap = midtransclient.Snap(
        is_production=False,
        server_key=os.getenv("MIDTRANS_SERVER_KEY")
    )
    param = {
        "transaction_details": {
            "order_id": f"{user_id}-{int(datetime.now().timestamp())}",
            "gross_amount": total_harga
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
    return {
        "snap_token": snap_token,
        "redirect_url": redirect_url
    }
@router.post("/callback")
async def midtrans_callback(request: Request):
    body = await request.json()
    print("MIDTRANS CALLBACK BODY:", body)

    order_id_raw = body.get("order_id")
    transaction_status = body.get("transaction_status")

    if not order_id_raw or not transaction_status:
        raise HTTPException(
            status_code=400,
            detail="order_id atau transaction_status tidak ditemukan di callback"
        )

    # Ambil id integer dari order_id (misal "7-1755006508" -> 7)
    try:
        order_id_int = int(str(order_id_raw).split("-")[0])
    except Exception:
        raise HTTPException(status_code=400, detail="Format order_id tidak valid")

    # Update status pembayaran di tabel payments
    supabase.table("payments").update({
        "status_pembayaran": transaction_status,
        "waktu_penyelesaian": body.get("settlement_time")
    }).eq("order_id", order_id_int).execute()

    # Jika sukses, update status order jadi 'paid' dan hapus cart
    if transaction_status in ["settlement", "capture"]:
    # Update order jadi paid
        supabase.table("orders").update({"status": "paid"}).eq("id", order_id_int).execute()

    # Cari user_id dari order
    order = supabase.table("orders").select("user_id").eq("id", order_id_int).execute()
    if order.data:
        user_id = order.data[0]["user_id"]
        # Hapus semua cart_items user itu
        supabase.table("cart_items").delete().eq("user_id", user_id).execute()

    return {
        "message": "Callback processed",
        "order_id": order_id_raw,
        "status": transaction_status
    }
