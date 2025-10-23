import firebase_admin
from firebase_admin import credentials, messaging
from ..config import supabase
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Inisialisasi Firebase Admin SDK (HANYA SEKALI saat aplikasi startup)
try:
    cred = credentials.Certificate(
        r"C:\Users\M. Rafly Al-Gybran\Downloads\kantinkuproject-firebase-adminsdk-fbsvc-243e27e816.json"
    )
    firebase_admin.initialize_app(cred)
    logger.info("Firebase Admin SDK berhasil diinisialisasi")
except ValueError:
    logger.info("Firebase Admin SDK sudah diinisialisasi sebelumnya")
except Exception as e:
    logger.error(f"Error saat inisialisasi Firebase: {e}")

def send_order_confirmed_notification(user_id: int, order_id: int):
    """
    Mengirim notifikasi bahwa pesanan sudah dikonfirmasi dan siap bayar.
    """
    logger.info(f"Menyiapkan notifikasi 'pesanan dikonfirmasi' untuk user_id: {user_id} (order_id: {order_id})")
    _send_notification_to_users(
        user_ids=[user_id],
        title='Pesanan Dikonfirmasi! ✅',
        body=f'Semua item untuk pesanan #{order_id} telah dikonfirmasi. Silakan lanjutkan ke pembayaran.',
        data={'order_id': str(order_id), 'type': 'order_confirmed'}
    )

def send_order_updated_notification(user_id: int, order_id: int):
    """
    Mengirim notifikasi bahwa ada update (penolakan item) pada pesanan.
    """
    logger.info(f"Menyiapkan notifikasi 'pesanan diperbarui' untuk user_id: {user_id} (order_id: {order_id})")
    _send_notification_to_users(
        user_ids=[user_id],
        title='Ada Pembaruan Pada Pesananmu 📝',
        body=f'Beberapa item untuk pesanan #{order_id} tidak tersedia. Silakan cek detail pesanan untuk melanjutkan.',
        data={'order_id': str(order_id), 'type': 'order_updated'}
    )

def _send_notification_to_users(user_ids: list[int], title: str, body: str, data: dict = None):
    """
    Fungsi generik untuk mengirim notifikasi ke daftar user ID.
    Ini adalah fungsi inti yang akan digunakan oleh fungsi notifikasi lainnya.
    """
    if not user_ids:
        logger.info("Tidak ada user ID, notifikasi dilewati.")
        return

    try:
        response = supabase.table("fcm_tokens").select("token").in_("user_id", user_ids).execute()
        
        if not response.data:
            logger.warning(f"Tidak ada token FCM untuk user_ids: {user_ids}")
            return

        registration_tokens = [item['token'] for item in response.data]
        if not registration_tokens:
            return
        
        logger.info(f"Ditemukan {len(registration_tokens)} token FCM untuk user_ids: {user_ids}")

        # ========================================================================
        # PERBAIKAN: Mengganti send_multicast dengan loop send() satu per satu
        # Ini untuk kompatibilitas dengan library firebase-admin versi lama.
        # ========================================================================
        success_count = 0
        failed_tokens = []

        for token in registration_tokens:
            try:
                message = messaging.Message(
                    notification=messaging.Notification(title=title, body=body),
                    data=data,
                    token=token,
                )
                messaging.send(message)
                success_count += 1
            except Exception as e:
                # Jika token tidak valid, Firebase akan memberikan error.
                # Kita kumpulkan token yang gagal ini.
                logger.error(f"Gagal mengirim ke token {token[:10]}...: {e}")
                failed_tokens.append(token)
        
        logger.info(f'Berhasil mengirim notifikasi ke {success_count} perangkat untuk users {user_ids}.')

        if failed_tokens:
            logger.warning(f"Menghapus {len(failed_tokens)} token yang tidak valid.")
            supabase.table("fcm_tokens").delete().in_("token", failed_tokens).execute()

    except Exception as e:
        logger.error(f"Error saat mengirim notifikasi ke users {user_ids}: {e}")


def send_order_ready_notification(user_id: int, order_id: int):
    """
    Mengirim notifikasi "Pesanan Siap" ke seorang pengguna.
    """
    logger.info(f"Menyiapkan notifikasi 'pesanan siap' untuk user_id: {user_id} (order_id: {order_id})")
    _send_notification_to_users(
        user_ids=[user_id],
        title='Pesananmu Sudah Siap! 🍜',
        # Perbarui body notifikasi agar lebih informatif
        body=f'Pesanan #{order_id} sudah siap untuk diambil. Selamat menikmati!',
        # Sertakan data tambahan untuk navigasi di aplikasi
        data={'order_id': str(order_id), 'type': 'order_ready'}
    )


def send_new_order_notification_to_staff(staff_ids: list[int], order_id: int):
    """
    Mengirim notifikasi "Pesanan Baru" ke daftar staff.
    """
    if not staff_ids:
        return
    
    logger.info(f"Menyiapkan notifikasi 'pesanan baru' untuk staff_ids: {staff_ids} (order_id: {order_id})")
    _send_notification_to_users(
        user_ids=staff_ids,
        title='Pesanan Baru Masuk! 🛎️',
        body=f'Ada pesanan baru (ID: {order_id}) yang perlu disiapkan. Segera cek inbox Anda.',
        data={'order_id': str(order_id), 'type': 'new_order'}
    )


def send_custom_notification(user_id: int, title: str, body: str, data: dict = None):
    """
    Mengirim notifikasi custom ke seorang pengguna.
    """
    logger.info(f"Menyiapkan notifikasi custom untuk user_id: {user_id}")
    _send_notification_to_users(
        user_ids=[user_id],
        title=title,
        body=body,
        data=data
    )