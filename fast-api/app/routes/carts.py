from fastapi import APIRouter, HTTPException, Depends, status
from typing import List
from ..models import CartItem, CartItemCreate, CartItemOut
from ..crud import fetch_carts
from .dependencies import get_current_user
from ..config import supabase

router = APIRouter(prefix="/carts", tags=["Carts"])

@router.get("/", response_model=List[CartItemOut])
def get_cart_items(current_user=Depends(get_current_user)):
    """Ambil semua item keranjang milik user yang login."""
    return [CartItemOut(**item) for item in fetch_carts({"user_id": current_user.id})]

@router.post("/", response_model=CartItemOut)
def add_cart_item(item: CartItemCreate, current_user=Depends(get_current_user)):
    """Tambah produk ke keranjang (jika sudah ada, update jumlah)."""
    try:
        # Cari cart item milik user dan produk ini
        existing_query = supabase.table("cart_items").select("*") \
            .eq("user_id", current_user.id).eq("product_id", item.product_id).execute()
        existing_list = existing_query.data or []
        existing = existing_list[0] if existing_list else None

        if existing:
            new_jumlah = existing["jumlah"] + item.jumlah
            updated = supabase.table("cart_items").update({"jumlah": new_jumlah}) \
                .eq("id", existing["id"]).execute().data
            if not updated or not isinstance(updated, list) or not updated[0]:
                raise HTTPException(status_code=500, detail="Gagal update cart")
            return CartItemOut(**updated[0])
        data = item.dict()
        data["user_id"] = current_user.id
        inserted = supabase.table("cart_items").insert(data).execute().data
        if not inserted or not isinstance(inserted, list) or not inserted[0]:
            raise HTTPException(status_code=500, detail="Gagal insert cart")
        return CartItemOut(**inserted[0])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")

@router.put("/{cart_item_id}", response_model=CartItemOut)
def update_cart_item(cart_item_id: int, item: CartItemCreate, current_user=Depends(get_current_user)):
    """Update jumlah produk di keranjang."""
    try:
        cart_query = supabase.table("cart_items").select("*").eq("id", cart_item_id).execute()
        cart_list = cart_query.data or []
        cart = cart_list[0] if cart_list else None
        if not cart or cart["user_id"] != current_user.id:
            raise HTTPException(status_code=404, detail="Item tidak ditemukan atau bukan milik Anda")
        updated = supabase.table("cart_items").update({"jumlah": item.jumlah, "product_id": item.product_id}) \
            .eq("id", cart_item_id).execute().data
        if not updated or not isinstance(updated, list) or not updated[0]:
            raise HTTPException(status_code=500, detail="Gagal update cart")
        return CartItemOut(**updated[0])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")

@router.delete("/{cart_item_id}")
def delete_cart_item(cart_item_id: int, current_user=Depends(get_current_user)):
    """Hapus produk dari keranjang."""
    cart_query = supabase.table("cart_items").select("*").eq("id", cart_item_id).execute()
    cart_list = cart_query.data or []
    cart = cart_list[0] if cart_list else None
    if not cart or cart["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Item tidak ditemukan atau bukan milik Anda")
    supabase.table("cart_items").delete().eq("id", cart_item_id).execute()
    return {"message": "Item berhasil dihapus dari keranjang"}