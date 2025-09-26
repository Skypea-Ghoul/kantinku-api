from fastapi import APIRouter, WebSocket

router = APIRouter()
active_connections = []

@router.websocket("/ws/payments/{user_id}")
async def payment_ws(websocket: WebSocket, user_id: int):
    await websocket.accept()
    active_connections.append((user_id, websocket))
    try:
        while True:
            await websocket.receive_text()
    except:
        active_connections.remove((user_id, websocket))

# Saat Midtrans callback sukses
async def notify_payment(user_id: int, order_id: str, status: str):
    for uid, ws in active_connections:
        if uid == user_id:
            await ws.send_json({"order_id": order_id, "status": status})
