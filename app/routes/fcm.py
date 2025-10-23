from fastapi import APIRouter, Depends, HTTPException, status
from ..models import FcmTokenCreate, UserOut
from .dependencies import get_current_user
from ..config import supabase
import logging

router = APIRouter(prefix="/api", tags=["FCM"])
logger = logging.getLogger(__name__)

@router.post("/fcm-token", status_code=status.HTTP_201_CREATED)
def register_fcm_token(token_data: FcmTokenCreate, current_user: UserOut = Depends(get_current_user)):
    """
    Menerima dan menyimpan FCM token dari user yang sedang login.
    
    PENTING: Setiap user hanya boleh punya 1 token aktif untuk menghindari notifikasi duplicate.
    Jika token baru didaftarkan, token lama untuk user tersebut akan dihapus.
    """
    token = token_data.token
    user_id = current_user.id

    try:
        # ✅ LANGKAH 1: Hapus SEMUA token lama milik user ini
        # Ini memastikan user hanya punya 1 token aktif
        logger.info(f"🧹 Membersihkan token lama untuk user_id: {user_id}")
        supabase.table("fcm_tokens").delete().eq("user_id", user_id).execute()
        
        # ✅ LANGKAH 2: Hapus token yang sama jika sudah terdaftar di user lain
        # Ini menghindari token duplicate dari device yang sama
        logger.info(f"🧹 Membersihkan token duplicate: {token[:20]}...")
        supabase.table("fcm_tokens").delete().eq("token", token).execute()
        
        # ✅ LANGKAH 3: Insert token baru
        logger.info(f"✅ Mendaftarkan token baru untuk user_id: {user_id}")
        supabase.table("fcm_tokens").insert({
            "user_id": user_id,
            "token": token,
        }).execute()

        return {"message": "FCM token registered successfully"}

    except Exception as e:
        logger.error(f"❌ Error saving FCM token: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save FCM token."
        )


@router.delete("/fcm-token/{token}", status_code=status.HTTP_200_OK)
def delete_fcm_token(token: str, current_user: UserOut = Depends(get_current_user)):
    """
    Menghapus FCM token tertentu dari database.
    Seorang user hanya bisa menghapus token yang terkait dengan akunnya.
    """
    try:
        logger.info(f"🗑️ Menghapus token untuk user_id: {current_user.id}")
        
        # Menghapus token berdasarkan nilainya yang unik dan memastikan
        # token tersebut milik user yang sedang login untuk keamanan.
        result = supabase.table("fcm_tokens").delete().eq("token", token).eq("user_id", current_user.id).execute()

        # result.data akan berisi list dari record yang dihapus.
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Token not found or you do not have permission to delete it."
            )

        logger.info(f"✅ Token berhasil dihapus untuk user_id: {current_user.id}")
        return {"message": "FCM token deleted successfully"}

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.error(f"❌ Error deleting FCM token: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete FCM token."
        )


@router.get("/fcm-token/count", status_code=status.HTTP_200_OK)
def get_user_token_count(current_user: UserOut = Depends(get_current_user)):
    """
    Endpoint untuk debugging: Mengecek berapa banyak token yang terdaftar untuk user ini.
    Idealnya hasilnya adalah 1.
    """
    try:
        result = supabase.table("fcm_tokens").select("token").eq("user_id", current_user.id).execute()
        token_count = len(result.data) if result.data else 0
        
        return {
            "user_id": current_user.id,
            "token_count": token_count,
            "tokens": [item['token'][:20] + "..." for item in result.data] if result.data else []
        }
    except Exception as e:
        logger.error(f"❌ Error getting token count: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get token count."
        )