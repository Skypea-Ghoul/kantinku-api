from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import users, products, categories, carts, orders, payments
from .auth import auth  # import routers lain di sini
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="E-Kantin API")

origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5173", # 🚀 Tambahkan domain frontend Anda di sini
    "http://127.0.0.1:5173",
    "https://300882d98b7d.ngrok-free.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # atau ganti dengan domain frontend kamu
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# include routers
app.include_router(users.router)
app.include_router(products.router)
app.include_router(categories.router)
app.include_router(carts.router)
app.include_router(orders.router)
app.include_router(auth.router)
app.include_router(payments.router)
# ...

# health check
@app.get("/health")
async def health_check():
    return {"status": "ok"}