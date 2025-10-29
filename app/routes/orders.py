from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, Query
from typing import List, Dict, Any, Optional
from ..models import Order, OrderItem, Order as OrderModel, UserOut, ProductSalesSummary, OrderCreate, OrderStatus
from ..crud import fetch_orders, is_product_owner, hitung_harga_jual
from .dependencies import get_current_user
from ..config import supabase
from datetime import datetime
from pydantic import BaseModel
from .websockets import manager
import json
import os
import midtransclient
import uuid
# ✅ Import hanya untuk notifikasi pesanan siap (bukan pesanan baru)
from ..services.notification_service import send_order_ready_notification, send_custom_notification, send_order_confirmed_notification

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
async def fetch_staff_order_inbox(
    order_status: str = Query(None, alias="status", description="Filter by order status"),
    include_items: bool = False,
    current_user: UserOut = Depends(get_current_user)
):
    """
    Mengambil semua pesanan yang produknya dimiliki oleh Staff yang login.
    """
    if current_user.role != "staff":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Hanya untuk staff."
        )

    try:
        # Re-implement the logic of the broken RPC function
        # 1. Get product_ids for the staff
        staff_products_response = supabase.table("product_users").select("product_id").eq("user_id", current_user.id).execute()
        staff_product_ids = [p['product_id'] for p in staff_products_response.data]

        if not staff_product_ids:
            return []

        # 2. Get unique order_ids containing these products
        order_items_response = supabase.table("order_items").select("order_id").in_("product_id", staff_product_ids).execute()
        order_ids = list(set(item['order_id'] for item in order_items_response.data))

        if not order_ids:
            return []

        # 3. Get the orders, with optional status filtering
        orders_query = supabase.table("orders").select("*").in_("id", order_ids)
        if order_status:
            orders_query = orders_query.eq("status", order_status)
        
        inbox_orders_query = orders_query.execute()

        if not inbox_orders_query.data:
            return []

        orders_list = inbox_orders_query.data

        # Include items if requested
        if include_items:
            order_ids = [order['id'] for order in orders_list]
            
            staff_products = supabase.table("product_users")\
                .select("product_id")\
                .eq("user_id", current_user.id)\
                .execute()
            
            staff_product_ids = [p['product_id'] for p in staff_products.data]
            
            if staff_product_ids:
                items = supabase.table("order_items")\
                    .select("*")\
                    .in_("order_id", order_ids)\
                    .in_("product_id", staff_product_ids)\
                    .execute()
                
                items_by_order = {}
                for item in items.data:
                    order_id = item['order_id']
                    if order_id not in items_by_order:
                        items_by_order[order_id] = []
                    items_by_order[order_id].append(item)
                
                for order in orders_list:
                    order['items'] = items_by_order.get(order['id'], [])

        return [Order(**order) for order in orders_list]

    except Exception as e:
        print(f"Error fetching staff inbox: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching orders: {str(e)}"
        )

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
async def create_order(order_details: OrderCreate, current_user: UserOut = Depends(get_current_user)):
    """
    Membuat order baru dari semua item di keranjang user dengan metode pembayaran.
    Status awal order: 'awaiting_confirmation'
    Status awal setiap item: 'awaiting_confirmation'
    """
    cart_items_resp = supabase.table("cart_items").select("*, products(*)").eq("user_id", current_user.id).execute()
    cart_items = cart_items_resp.data
    
    if not cart_items:
        raise HTTPException(status_code=400, detail="Keranjang belanja kosong")
    
    total_harga = sum(item['products']['harga'] * item['jumlah'] for item in cart_items)
    
    status_order = "awaiting_confirmation"
    current_time_str = datetime.now().isoformat()
    
    order_data = {
        "user_id": current_user.id,
        "status": status_order,
        "total_harga": total_harga,
        "tanggal_pesanan": current_time_str,
        "catatan": order_details.catatan,
        "payment_method": order_details.payment_method,
    }
    
    order_insert_resp = supabase.table("orders").insert(order_data).execute()
    
    if not order_insert_resp.data:
        raise HTTPException(status_code=500, detail="Gagal membuat pesanan")
    
    order = order_insert_resp.data[0]
    new_order_id = order['id']
    
    # Create order items with status 'awaiting_confirmation'
    order_items_to_create = [
        {
            "order_id": new_order_id,
            "product_id": item['product_id'],
            "jumlah": item['jumlah'],
            "harga_unit": item['products']['harga'],
            "subtotal": item['products']['harga'] * item['jumlah'],
            "status": "awaiting_confirmation",  # ✅ Tambahkan status
        }
        for item in cart_items
    ]

    supabase.table("order_items").insert(order_items_to_create).execute()
    supabase.table("cart_items").delete().eq("user_id", current_user.id).execute()

    product_ids_in_order = [item['product_id'] for item in cart_items]

    if product_ids_in_order:
        # 2. Cari semua staff (user_id) yang memiliki produk-produk tersebut
        staff_query = supabase.table("product_users")\
            .select("user_id")\
            .in_("product_id", product_ids_in_order)\
            .execute()

        if staff_query.data:
            # 3. Dapatkan daftar ID staff yang unik (menghindari duplikat notif)
            staff_ids = list(set(staff['user_id'] for staff in staff_query.data))
            
            # 4. Siapkan payload notifikasi
            notification_payload = json.dumps({
                "type": "new_order",
                "order_id": new_order_id,
                "message": f"Pesanan baru #{new_order_id} telah masuk!"
            })
            
            print(f"\n--- 🖥️  BACKEND: MEMPROSES NOTIFIKASI PESANAN BARU ---")
            print(f"Pesanan Dibuat: #{new_order_id}")
            print(f"Staff yang relevan ditemukan: {staff_ids}")

            # 5. Kirim notifikasi ke setiap staff yang relevan
            for staff_id in staff_ids:
                print(f">>> Mengirim payload ke staff ID #{staff_id}...")
                await manager.broadcast_to_user(staff_id, notification_payload)
            
            print(f"--- ✅ BACKEND: Selesai mengirim notifikasi ---\n")
   
    return Order(**order)

@router.get("/{order_id}/staff-confirmation-status", tags=["Staff Actions"])
async def check_staff_confirmation_status(
    order_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """
    Check if current staff has confirmed their items in this order.
    Also returns total staff count and how many have confirmed.
    """
    if current_user.role != "staff":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya staff yang dapat mengakses endpoint ini"
        )

    # Get order
    order_query = supabase.table("orders").select("*").eq("id", order_id).single().execute()
    if not order_query.data:
        return {
            "has_confirmed": False,
            "has_items": False,
            "message": "Pesanan tidak ditemukan"
        }

    # Get ALL order items for this order
    all_items_query = supabase.table("order_items")\
        .select("product_id, status")\
        .eq("order_id", order_id)\
        .execute()
    
    all_items = all_items_query.data
    
    if not all_items:
        return {
            "has_confirmed": False,
            "has_items": False,
            "message": "Tidak ada item dalam pesanan ini"
        }

    # Get unique product IDs
    product_ids = list(set(item['product_id'] for item in all_items))
    
    # Get staff for each product
    product_staff_query = supabase.table("product_users")\
        .select("product_id, user_id")\
        .in_("product_id", product_ids)\
        .execute()
    
    # Group by staff - setiap staff yang punya produk dalam order ini
    staff_products = {}
    for ps in product_staff_query.data:
        staff_id = ps['user_id']
        product_id = ps['product_id']
        if staff_id not in staff_products:
            staff_products[staff_id] = []
        staff_products[staff_id].append(product_id)
    
    total_staff = len(staff_products)
    
    # Check confirmation status per staff
    confirmed_staff_count = 0
    current_staff_confirmed = False
    current_staff_has_items = False
    
    for staff_id, staff_product_list in staff_products.items():
        # Get items for this staff
        staff_items = [item for item in all_items if item['product_id'] in staff_product_list]
        
        if staff_items:
            # Check if all items for this staff are confirmed
            all_confirmed = all(item['status'] == 'confirmed' for item in staff_items)
            any_rejected = any(item['status'] == 'rejected' for item in staff_items)
            
            # Staff dianggap sudah konfirmasi jika semua itemnya confirmed atau rejected
            if all_confirmed or any_rejected:
                confirmed_staff_count += 1
            
            # Check if current staff
            if staff_id == current_user.id:
                current_staff_has_items = True
                current_staff_confirmed = (all_confirmed or any_rejected)
    
    return {
        "has_confirmed": current_staff_confirmed,
        "has_items": current_staff_has_items,
        "total_staff": total_staff,
        "confirmed_staff_count": confirmed_staff_count,
        "message": f"{confirmed_staff_count} dari {total_staff} staff telah konfirmasi"
    }

@router.put("/{order_id}/confirm", response_model=Order, tags=["Staff Actions"]) 
async def confirm_order(
    order_id: int,
    action_update: dict,  # {"action": "accept"} or {"action": "reject"}
    current_user: UserOut = Depends(get_current_user)
):
    """
    Staff confirms or rejects an order.
    - action="accept": Changes status to "awaiting_payment" and auto-generates Snap URL for QRIS
    - action="reject": Changes status to "cancelled"
    """
    if current_user.role != "staff":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Hanya staff yang dapat mengkonfirmasi pesanan"
        )

    action = action_update.get("action")

    # Validate action
    if action not in ["accept", "reject"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Action harus "accept" atau "reject"'
        )

    # Get order data
    order_query = supabase.table("orders").select("*").eq("id", order_id).single().execute()
    
    if not order_query.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Pesanan tidak ditemukan"
        )

    order = order_query.data
    
    if order['status'] != 'awaiting_confirmation':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Pesanan tidak dapat dikonfirmasi karena statusnya adalah '{order['status']}'"
        )

    # If reject, just update status and send notification
    if action == "reject":
        updated_order = supabase.table("orders").update({
            "status": "cancelled"
        }).eq("id", order_id).execute()

        if not updated_order.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Gagal memperbarui status pesanan"
            )

        customer_id = order['user_id']
        send_custom_notification(
            user_id=customer_id,
            title="Pesanan Dibatalkan ❌",
            body=f"Maaf, pesanan #{order_id} tidak dapat diproses dan telah dibatalkan.",
            data={
                "order_id": str(order_id),
                "type": "order_cancelled"
            }
        )

        return updated_order.data[0]

    # If accept, update status and generate Snap URL for QRIS
    update_data = {"status": "awaiting_payment"}
    snap_redirect_url = None

    # Check if payment method is QRIS
    payment_method = order.get('payment_method', '').lower()
    
    if payment_method == 'qris':
        try:
            # Step 1: Fetch order items
            order_items_query = supabase.table("order_items")\
                .select("product_id, jumlah, harga_unit")\
                .eq("order_id", order_id)\
                .execute()
            
            if not order_items_query.data:
                print(f"⚠️ No order items found for order {order_id}")
                raise Exception("Tidak ada item dalam pesanan ini")
            
            order_items = order_items_query.data
            
            # Step 2: Fetch product details for each item
            product_ids = [item['product_id'] for item in order_items]
            products_query = supabase.table("products")\
                .select("id, nama_produk, harga")\
                .in_("id", product_ids)\
                .execute()
            
            if not products_query.data:
                print(f"⚠️ No products found for order items")
                raise Exception("Produk tidak ditemukan")
            
            # Create a map of product_id to product data
            products_map = {p['id']: p for p in products_query.data}

            # Calculate prices
            fee_qris = 0.7
            biaya_tetap = 500
            ppn_persen = 11

            item_details = []
            subtotal_harga_awal = 0
            
            for item in order_items:
                product_id = item['product_id']
                product = products_map.get(product_id)
                
                if not product:
                    print(f"⚠️ Product {product_id} not found in products_map")
                    continue
                
                # Use harga_unit from order_item (harga saat order dibuat)
                harga_awal = int(item['harga_unit'])
                jumlah = int(item['jumlah'])
                
                item_details.append({
                    "id": str(product_id),
                    "price": harga_awal,
                    "quantity": jumlah,
                    "name": product['nama_produk']
                })
                subtotal_harga_awal += harga_awal * jumlah

            if not item_details:
                raise Exception("Tidak ada item valid untuk diproses")

            # Calculate final price with service fees
            harga_jual_akhir = hitung_harga_jual(subtotal_harga_awal, biaya_tetap, fee_qris, ppn_persen)
            biaya_layanan = harga_jual_akhir - subtotal_harga_awal
            
            if biaya_layanan > 0:
                item_details.append({
                    "id": "SERVICE_FEE",
                    "price": biaya_layanan,
                    "quantity": 1,
                    "name": "Biaya Layanan & Pajak"
                })

            # Create unique Midtrans order ID
            unique_midtrans_order_id = f"{order_id}-{uuid.uuid4().hex[:6]}"

            # Get customer data
            customer_query = supabase.table("users")\
                .select("nama_pengguna, nomor_telepon")\
                .eq("id", order['user_id'])\
                .single()\
                .execute()
            
            customer = customer_query.data if customer_query.data else {}

            # Initialize Midtrans Snap
            snap = midtransclient.Snap(
                is_production=False,
                server_key=os.getenv("MIDTRANS_SERVER_KEY")
            )

            # Prepare transaction parameters
            param = {
                "transaction_details": {
                    "order_id": unique_midtrans_order_id,
                    "gross_amount": harga_jual_akhir
                },
                "item_details": item_details,
                "enabled_payments": ["gopay"],
                "customer_details": {
                    "first_name": customer.get('nama_pengguna', 'Customer'),
                    "phone": customer.get('nomor_telepon', '')
                }
            }

            # Create Snap transaction
            transaction = snap.create_transaction(param)
            snap_redirect_url = transaction.get('redirect_url')

            if snap_redirect_url:
                update_data["snap_redirect_url"] = snap_redirect_url
                update_data["total_harga"] = harga_jual_akhir

            print(f"✅ Snap URL generated for order {order_id}: {snap_redirect_url}")

        except Exception as e:
            print(f"❌ Error generating Snap URL for order {order_id}: {str(e)}")
            import traceback
            traceback.print_exc()
            # Continue with order confirmation even if Snap URL generation fails
            # Staff can generate it manually later if needed

    # Update order with new status (and Snap URL if QRIS)
    updated_order = supabase.table("orders").update(update_data).eq("id", order_id).execute()

    if not updated_order.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gagal memperbarui status pesanan"
        )

    # Send notification to customer
    customer_id = order['user_id']
    
    if payment_method == 'qris' and snap_redirect_url:
        send_order_confirmed_notification(
            user_id=customer_id,
            order_id=order_id
        )
    elif payment_method == 'cash':
        send_custom_notification(
            user_id=customer_id,
            title="Pesanan Dikonfirmasi ✅",
            body=f"Pesanan #{order_id} telah dikonfirmasi. Silakan selesaikan pembayaran tunai.",
            data={
                "order_id": str(order_id),
                "type": "order_confirmed"
            }
        )
    else:
        # QRIS but failed to generate Snap URL
        send_custom_notification(
            user_id=customer_id,
            title="Pesanan Dikonfirmasi ✅",
            body=f"Pesanan #{order_id} telah dikonfirmasi. Mohon hubungi staff untuk pembayaran.",
            data={
                "order_id": str(order_id),
                "type": "order_confirmed"
            }
        )

    return updated_order.data[0]

# Tambahkan endpoint baru untuk konfirmasi per-item oleh staff

@router.put("/{order_id}/confirm-items", response_model=Order, tags=["Staff Actions"]) 
async def confirm_order_items(
    order_id: int,
    action_update: dict,  # {"action": "accept"} or {"action": "reject"}
    current_user: UserOut = Depends(get_current_user)
):
    """
    Staff confirms or rejects their own order items.
    Order proceeds to payment ONLY IF ALL staff accept.
    If ANY staff rejects, the entire order is cancelled.
    """
    if current_user.role != "staff":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Hanya staff yang dapat mengkonfirmasi pesanan"
        )

    action = action_update.get("action")
    if action not in ["accept", "reject"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Action harus "accept" atau "reject"'
        )

    order_query = supabase.table("orders").select("*").eq("id", order_id).single().execute()
    if not order_query.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pesanan tidak ditemukan")
    order = order_query.data
    
    if order['status'] != 'awaiting_confirmation':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Pesanan tidak dapat dikonfirmasi karena statusnya adalah '{order['status']}'"
        )

    staff_products_query = supabase.table("product_users").select("product_id").eq("user_id", current_user.id).execute()
    staff_product_ids = [p['product_id'] for p in staff_products_query.data]
    if not staff_product_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Anda tidak memiliki produk dalam pesanan ini")

    staff_items_query = supabase.table("order_items").select("id, status").eq("order_id", order_id).in_("product_id", staff_product_ids).execute()
    staff_items = staff_items_query.data
    if not staff_items:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tidak ada item Anda dalam pesanan ini")
    
    if any(item['status'] != 'awaiting_confirmation' for item in staff_items):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Anda sudah mengkonfirmasi item Anda untuk pesanan ini")

    # --- AWAL DARI LOGIKA BARU YANG LEBIH KETAT ---

    # 1. Update status untuk semua item milik staff ini
    new_item_status = "confirmed" if action == "accept" else "rejected"
    staff_item_ids = [item['id'] for item in staff_items]
    updated_items = supabase.table("order_items").update({"status": new_item_status}).in_("id", staff_item_ids).execute()
    if not updated_items.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Gagal memperbarui status item")

    # 2. Ambil status SEMUA item untuk order ini setelah di-update
    all_items_query = supabase.table("order_items").select("status").eq("order_id", order_id).execute()
    all_items_statuses = [item['status'] for item in all_items_query.data]

    # 3. Cek apakah masih ada item yang menunggu konfirmasi dari staff lain
    if 'awaiting_confirmation' in all_items_statuses:
        # Kirim notifikasi progres ke customer
        confirmed_count = all_items_statuses.count('confirmed')
        rejected_count = all_items_statuses.count('rejected')
        total_items = len(all_items_statuses)
        
        send_custom_notification(
            user_id=order['user_id'],
            title="Update Konfirmasi Pesanan ⏳",
            body=f"Pesanan #{order_id}: {confirmed_count + rejected_count}/{total_items} staff telah merespon.",
            data={"order_id": str(order_id), "type": "order_partial_confirmation"}
        )
        return Order(**order) # Kembalikan order apa adanya, proses belum selesai

    # 4. Jika SEMUA staff sudah merespon (tidak ada lagi 'awaiting_confirmation')
    else:
        # Skenario A: ADA SATU SAJA item yang ditolak, batalkan seluruh pesanan
        if 'rejected' in all_items_statuses:
            updated_order_q = supabase.table("orders").update({
                "status": "cancelled",
                "total_harga": 0
            }).eq("id", order_id).execute()
            
            send_custom_notification(
                user_id=order['user_id'],
                title="Pesanan Dibatalkan ❌",
                body=f"Maaf, pesanan #{order_id} tidak dapat diproses karena sebagian item tidak tersedia.",
                data={"order_id": str(order_id), "type": "order_cancelled"}
            )
            return updated_order_q.data[0]

        # Skenario B: SEMUA item diterima (tidak ada 'rejected' dan tidak ada 'awaiting_confirmation')
        else:
            update_data = {"status": "awaiting_payment"}
            snap_redirect_url = None
            payment_method = order.get('payment_method', '').lower()
            
            if payment_method == 'qris':
                try:
                    # Logika generate Snap URL Anda sudah benar, kita gunakan lagi di sini
                    # Fetch order items with product details
                    order_items_query = supabase.table("order_items").select("product_id, jumlah, harga_unit").eq("order_id", order_id).execute()
                    order_items = order_items_query.data
                    
                    product_ids = [item['product_id'] for item in order_items]
                    products_query = supabase.table("products").select("id, nama_produk, harga").in_("id", product_ids).execute()
                    products_map = {p['id']: p for p in products_query.data}

                    fee_qris = 0.7
                    biaya_tetap = 500
                    ppn_persen = 11

                    item_details = []
                    subtotal_harga_awal = 0
                    
                    for item in order_items:
                        product_id = item['product_id']
                        product = products_map.get(product_id)
                        
                        if not product:
                            continue
                        
                        harga_awal = int(item['harga_unit'])
                        jumlah = int(item['jumlah'])
                        
                        item_details.append({
                            "id": str(product_id),
                            "price": harga_awal,
                            "quantity": jumlah,
                            "name": product['nama_produk']
                        })
                        subtotal_harga_awal += harga_awal * jumlah

                    if not item_details:
                        raise Exception("Tidak ada item valid untuk diproses")

                    # Calculate final price with service fees
                    harga_jual_akhir = hitung_harga_jual(subtotal_harga_awal, biaya_tetap, fee_qris, ppn_persen)
                    biaya_layanan = harga_jual_akhir - subtotal_harga_awal
                    
                    if biaya_layanan > 0:
                        item_details.append({
                            "id": "SERVICE_FEE",
                            "price": biaya_layanan,
                            "quantity": 1,
                            "name": "Biaya Layanan & Pajak"
                        })

                    # Create unique Midtrans order ID
                    unique_midtrans_order_id = f"{order_id}-{uuid.uuid4().hex[:6]}"

                    # Get customer data
                    customer_query = supabase.table("users")\
                        .select("nama_pengguna, nomor_telepon")\
                        .eq("id", order['user_id'])\
                        .single()\
                        .execute()
                    
                    customer = customer_query.data if customer_query.data else {}

                    # Initialize Midtrans Snap
                    snap = midtransclient.Snap(
                        is_production=False,
                        server_key=os.getenv("MIDTRANS_SERVER_KEY")
                    )

                    # Prepare transaction parameters
                    param = {
                        "transaction_details": {
                            "order_id": unique_midtrans_order_id,
                            "gross_amount": harga_jual_akhir
                        },
                        "item_details": item_details,
                        "enabled_payments": ["gopay"],
                        "customer_details": {
                            "first_name": customer.get('nama_pengguna', 'Customer'),
                            "phone": customer.get('nomor_telepon', '')
                        }
                    }

                    # Create Snap transaction
                    transaction = snap.create_transaction(param)
                    snap_redirect_url = transaction.get('redirect_url')

                    if snap_redirect_url:
                        update_data["snap_redirect_url"] = snap_redirect_url
                        update_data["total_harga"] = harga_jual_akhir

                    print(f"✅ Snap URL generated for order {order_id}: {snap_redirect_url}")

                except Exception as e:
                    print(f"❌ Error generating Snap URL for fully confirmed order {order_id}: {str(e)}")

            # Update order ke status awaiting_payment
            final_updated_order_q = supabase.table("orders").update(update_data).eq("id", order_id).execute()
            send_order_confirmed_notification(user_id=order['user_id'], order_id=order_id)

            customer_id = order['user_id']
            notification_payload = json.dumps({
                "type": "order_status_update", 
                "order_id": order_id, 
                "new_status": "awaiting_payment" # Status baru
            })
            print(f"📢 Mengirim notifikasi WebSocket 'order_status_update' ke user #{customer_id}")
            await manager.broadcast_to_user(customer_id, notification_payload)

            return final_updated_order_q.data[0]
        
@router.put("/{order_id}/mark-as-paid", response_model=Order, tags=["Staff Actions"])
async def mark_order_as_paid(
    order_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """
    Staff marks a cash order as paid.
    Changes order status AND all its confirmed items' status to "paid".
    """
    if current_user.role != "staff":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya staff yang dapat menandai pesanan sebagai dibayar"
        )

    # Get order data first
    order_query = supabase.table("orders").select("*").eq("id", order_id).single().execute()
    if not order_query.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pesanan tidak ditemukan"
        )

    order = order_query.data
    if order['status'] != 'awaiting_payment':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Pesanan tidak dapat ditandai sebagai dibayar karena statusnya adalah '{order['status']}'"
        )

    # 1. Update status order utama menjadi "paid"
    updated_order_q = supabase.table("orders").update({
        "status": "paid"
    }).eq("id", order_id).execute()

    if not updated_order_q.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gagal memperbarui status pesanan"
        )
    
    # ✅ --- LOGIKA BARU DITAMBAHKAN DI SINI ---
    # 2. Update semua item yang 'confirmed' di dalam order ini menjadi 'paid'
    supabase.table("order_items").update({
        "status": "paid"
    }).eq("order_id", order_id).eq("status", "confirmed").execute()
    # ---------------------------------------------

    # 3. Kirim notifikasi ke customer
    customer_id = order['user_id']
    send_custom_notification(
        user_id=customer_id,
        title="Pembayaran Diterima ✅",
        body=f"Pembayaran untuk pesanan #{order_id} telah diterima. Pesanan Anda sedang diproses.",
        data={
            "order_id": str(order_id),
            "type": "payment_confirmed"
        }
    )

    notification_payload = json.dumps({
        "type": "order_status_update", 
        "order_id": order_id, 
        "new_status": "paid" # Status baru
    })
    print(f"📢 Mengirim notifikasi WebSocket 'order_status_update' (paid) ke user #{customer_id}")
    await manager.broadcast_to_user(customer_id, notification_payload)

    return updated_order_q.data[0]

@router.post("/{order_id}/generate-snap", response_model=Dict[str, Optional[str]], tags=["Payments"])
async def generate_snap_url(
    order_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """
    Membuat Snap Redirect URL dari Midtrans untuk pesanan yang sudah ada.
    Hanya untuk pesanan dengan status 'awaiting_payment'.
    """
    # 1. Ambil data pesanan dan validasi
    order_query = supabase.table("orders").select("*").eq("id", order_id).single().execute()
    if not order_query.data:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")

    order = order_query.data
    if order['user_id'] != current_user.id:
        raise HTTPException(status_code=403, detail="Anda tidak memiliki akses ke pesanan ini")

    if order['status'] != 'awaiting_payment':
        raise HTTPException(
            status_code=400,
            detail=f"Link pembayaran hanya bisa dibuat untuk pesanan dengan status 'awaiting_payment'. Status saat ini: '{order['status']}'"
        )

    # 2. Ambil detail item pesanan
    order_items_query = supabase.table("order_items").select("*, products(nama_produk, harga)").eq("order_id", order_id).execute()
    if not order_items_query.data:
        raise HTTPException(status_code=404, detail="Item untuk pesanan ini tidak ditemukan")

    order_items = order_items_query.data

    # 3. Hitung total harga dan siapkan item_details untuk Midtrans
    fee_qris = 0.7
    biaya_tetap = 500
    ppn_persen = 11

    item_details = []
    subtotal_harga_awal = 0
    for item in order_items:
        harga_awal = int(item["products"]["harga"])
        jumlah = int(item["jumlah"])
        item_details.append({
            "id": str(item["product_id"]),
            "price": harga_awal,
            "quantity": jumlah,
            "name": item["products"]["nama_produk"]
        })
        subtotal_harga_awal += harga_awal * jumlah

    # 4. Hitung harga jual akhir termasuk biaya layanan
    harga_jual_akhir = hitung_harga_jual(subtotal_harga_awal, biaya_tetap, fee_qris, ppn_persen)
    biaya_layanan = harga_jual_akhir - subtotal_harga_awal
    if biaya_layanan > 0:
        item_details.append({"id": "SERVICE_FEE", "price": biaya_layanan, "quantity": 1, "name": "Biaya Layanan & Pajak"})

    # 5. Buat order_id unik untuk Midtrans untuk menghindari error duplicate
    unique_midtrans_order_id = f"{order_id}-{uuid.uuid4().hex[:6]}"

    # 6. Inisialisasi Midtrans Snap client
    snap = midtransclient.Snap(
        is_production=False,
        server_key=os.getenv("MIDTRANS_SERVER_KEY")
    )

    # 7. Siapkan parameter untuk Midtrans
    param = {
        "transaction_details": {
            "order_id": unique_midtrans_order_id,
            "gross_amount": harga_jual_akhir
        },
        "item_details": item_details,
        "enabled_payments": ["gopay"], # Sesuaikan dengan metode pembayaran yang Anda inginkan
        "customer_details": {
            "first_name": current_user.nama_pengguna,
            "phone": current_user.nomor_telepon
        }
    }

    # 8. Buat transaksi Snap
    try:
        transaction = snap.create_transaction(param)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal membuat transaksi Midtrans: {e}")

    redirect_url = transaction.get('redirect_url')

    # 9. Simpan redirect_url dan total harga baru ke database
    if redirect_url:
        supabase.table("orders").update({
            "snap_redirect_url": redirect_url,
            "total_harga": harga_jual_akhir # Update total harga jika ada biaya layanan
        }).eq("id", order_id).execute()

    # 10. Kembalikan URL ke client
    return {"snap_url": redirect_url}

@router.get("/{order_id}/status", response_model=OrderStatus)
async def get_order_status(order_id: int, current_user: UserOut = Depends(get_current_user)):
    """
    Mendapatkan status pesanan saat ini.
    Dapat diakses oleh pemilik pesanan atau staff.
    """
    order_resp = supabase.table("orders").select("status, user_id").eq("id", order_id).single().execute()

    if not order_resp.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pesanan tidak ditemukan")

    order_data = order_resp.data
    if order_data['user_id'] != current_user.id and current_user.role != "staff":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Anda tidak memiliki akses ke status pesanan ini")

    return {"status": order_data['status']}


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