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

router = APIRouter(prefix="/payments", tags=["Payments"])

class SnapTokenRequest(BaseModel):
    user_id: int
    cart_ids: List[int] # ID dari item-item di keranjang yang akan di-checkout

@router.post("/snap-token")
def get_snap_token(data: SnapTokenRequest):
    user_id = data.user_id
    cart_ids = data.cart_ids

    # FIX: Ambil data user di awal agar tidak error saat digunakan nanti
    user = supabase.table("users").select("nama_pengguna, nomor_telepon").eq("id", user_id).single().execute().data
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
    for cart_item in cart_items:
        product = supabase.table("products").select("nama_produk,harga").eq("id", cart_item["product_id"]).single().execute().data
        harga_awal = int(product["harga"])
        harga_jual, markup = hitung_harga_jual(harga_awal, target_untung, fee_qris)
        item_details.append({
            "id": str(cart_item["product_id"]),
            "price": harga_jual,
            "quantity": int(cart_item["jumlah"]),
            "name": product["nama_produk"]
        })
        total_harga += harga_jual * int(cart_item["jumlah"])
    
    # 1. Buat Order baru di database dengan status 'pending'
    order_data = {
        "user_id": user_id,
        "status": "pending",
        "total_harga": total_harga,
        "tanggal_pesanan": datetime.now().isoformat(),
    }
    order_insert_res = supabase.table("orders").insert(order_data).execute()
    if not order_insert_res.data:
        raise HTTPException(status_code=500, detail="Gagal membuat order di database.")
    
    new_order = order_insert_res.data[0]
    order_id = new_order['id'] # Ini adalah ID integer dari database

    # 2. Buat OrderItems berdasarkan cart_items
    order_items_to_create = []
    for cart_item in cart_items:
        product = supabase.table("products").select("harga").eq("id", cart_item["product_id"]).single().execute().data
        order_items_to_create.append({
            "order_id": order_id,
            "product_id": cart_item["product_id"],
            "jumlah": cart_item["jumlah"],
            "harga_unit": product['harga'], # Harga asli produk
            "subtotal": cart_item["jumlah"] * product['harga']
        })
    supabase.table("order_items").insert(order_items_to_create).execute()

    # 3. Buat record 'payments' awal dengan status 'pending'
    initial_payment_data = {
        "order_id": order_id,
        "transaksi_id": f"pending-{order_id}", # FIX: Tambahkan placeholder untuk transaksi_id
        "transaction_status": "pending",
        "gross_amount": total_harga,
        "payment_type": "qris" # Default, akan diupdate oleh callback
    }
    supabase.table("payments").insert(initial_payment_data).execute()

    snap = midtransclient.Snap(
        is_production=False,
        server_key=os.getenv("MIDTRANS_SERVER_KEY")
    )

    param = {
        "transaction_details": {
            "order_id": str(order_id), # Kirim ID integer sebagai string
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
    
    # TODO: Dalam produksi, validasi signature_key Midtrans di sini untuk keamanan.
    
    print("MIDTRANS CALLBACK BODY:", body)

    order_id_raw = body.get("order_id")
    transaction_status = body.get("transaction_status")

    if not order_id_raw or not transaction_status:
        raise HTTPException(status_code=400, detail="Data callback wajib hilang")

    try:
        # order_id sekarang adalah integer murni dari Midtrans
        order_id_int = int(order_id_raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Format order_id dari callback tidak valid")
        
    # 1. Tentukan status pembayaran akhir
    if transaction_status in ["settlement", "capture"]:
        final_order_status = "paid"
    elif transaction_status in ["pending", "authorize"]:
        final_order_status = "pending"
    else:
        final_order_status = "cancelled"

    # 2. Siapkan data untuk tabel 'payments'
    payment_data = {
        "order_id": order_id_int,
        "transaksi_id": body.get("transaction_id"),
        "status_code": body.get("status_code"),
        "transaction_status": transaction_status,
        "gross_amount": float(body.get("gross_amount")),
        "payment_type": body.get("payment_type"),
        "qr_code_url": body.get("qr_code_url"),
        "transaction_time": body.get("transaction_time"),
        "settlement_time": body.get("settlement_time"),
        "signature_key": body.get("signature_key"),
    }
    
    # 3. Update Data Pembayaran. Ini harus cepat.
    supabase.table("payments").update(payment_data).eq("order_id", order_id_int).execute()

    # 4. Jika pembayaran sukses, update status order dan hapus keranjang.
    if final_order_status == "paid":
        # Lakukan update status order dan ambil user_id dalam satu panggilan jika memungkinkan
        # atau lakukan secara berurutan tapi pastikan cepat.
        supabase.table("orders").update({"status": "paid"}).eq("id", order_id_int).execute()

        # Asumsi update berhasil, kita perlu user_id untuk menghapus keranjang.
        # Kita bisa query lagi atau idealnya, jika mungkin, dapatkan dari respons update.
        # Untuk kesederhanaan, kita query lagi.
        order_query = supabase.table("orders").select("user_id").eq("id", order_id_int).single().execute()
        if order_query.data:
            user_id = order_query.data["user_id"]
            # Hapus item keranjang yang sudah di-checkout.
            # NOTE: Ini akan menghapus SEMUA item di keranjang user, bukan hanya yang di-checkout.
            supabase.table("cart_items").delete().eq("user_id", user_id).execute()
            print(f"Cart items for user {user_id} deleted successfully.")
    
    # 5. Jika statusnya 'pending' (misal GoPay baru dibuat), kita tidak menghapus cart/mengubah status order menjadi paid.

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
    # 1. Verifikasi apakah order ada dan milik user yang login
    order_query = supabase.table("orders").select("user_id").eq("id", order_id).single().execute()
    
    if not order_query.data:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan.")
    
    # Verifikasi kepemilikan
    if order_query.data["user_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Akses ditolak.")
        
    # 2. Ambil detail pembayaran terkait
    payment_details_query = supabase.table("payments").select("*").eq("order_id", order_id).execute()
    
    if not payment_details_query.data:
        # NOTE: Jika tidak ada record pembayaran, ini BUKAN 404, tapi 200 dengan list kosong
        return [] 
        
    # 3. Kembalikan data
    return [Payment(**p) for p in payment_details_query.data]