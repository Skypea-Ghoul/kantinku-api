# file: routers/websockets.py

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends, status
from typing import List, Dict

# Import dependency untuk validasi token
from .dependencies import get_user_from_ws_token 
from ..models import UserOut
import json
from ..config import supabase

# ... (Kode ConnectionManager Anda tetap sama) ...
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        print(f"✅ WS Terhubung: User #{user_id} terkoneksi. Total koneksi: {len(self.active_connections[user_id])}")

    def disconnect(self, websocket: WebSocket, user_id: int):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
        print(f"🔌 WS Terputus: User #{user_id} disconnect.")

    async def broadcast_to_user(self, user_id: int, message: str):
        if user_id in self.active_connections:
            connections = self.active_connections[user_id][:]
            for connection in connections:
                try:
                    await connection.send_text(message)
                except Exception:
                    self.disconnect(connection, user_id)

manager = ConnectionManager()
router = APIRouter()


# ✅ --- INI ADALAH FUNGSI YANG DIPERBAIKI ---
@router.websocket("/ws/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket, 
    user_id: int, 
    # FastAPI akan menjalankan dependency ini dan memberikan hasilnya (UserOut)
    # atau menolak koneksi secara otomatis jika token tidak valid.
    user: UserOut = Depends(get_user_from_ws_token) 
):
    """
    Endpoint ini menerima koneksi WebSocket. Validasi token dan user ID
    ditangani secara otomatis oleh dependency 'get_user_from_ws_token'.
    """
    # Pastikan user dari token cocok dengan user_id di path
    if user.id != user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        print(f"❌ WS Gagal: Token valid, tapi user ID tidak cocok ({user.id} != {user_id})")
        return

    # Jika kode sampai di sini, user sudah pasti terotentikasi.
    await manager.connect(websocket, user.id)
    
    try:
        # Loop ini menjaga koneksi tetap hidup
        while True:
            await websocket.receive_text()
            
    except WebSocketDisconnect:
        manager.disconnect(websocket, user.id)
    except Exception:
        manager.disconnect(websocket, user.id)

async def notify_all_staff_of_product_change():
    """
    Finds all connected users with the 'staff' role and sends them
    a product update notification.
    """
    # Get all user IDs that are currently connected via WebSocket
    connected_user_ids = list(manager.active_connections.keys())

    if not connected_user_ids:
        return # No one is connected, do nothing

    # From the connected users, find out which ones are staff
    try:
        staff_query = supabase.table("users")\
            .select("id")\
            .in_("id", connected_user_ids)\
            .eq("role", "staff")\
            .execute()

        staff_ids = [user['id'] for user in staff_query.data]
        
        if staff_ids:
            print(f"📢 Notifying staff of product update: {staff_ids}")
            payload = json.dumps({"type": "product_update"})
            for staff_id in staff_ids:
                await manager.broadcast_to_user(staff_id, payload)

    except Exception as e:
        print(f"❌ Error during staff notification broadcast: {e}")