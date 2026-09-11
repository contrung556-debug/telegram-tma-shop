import os
import asyncio
import threading
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

# ==================== CẤU HÌNH HỆ THỐNG ====================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.getenv("DATABASE_URL")
TOKEN = os.getenv("TELEGRAM_TOKEN")
MINI_APP_URL = "https://github.io"
WEBHOOK_API_KEY = "SECRET_SEPAY_KEY_123"

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

# Khởi tạo database trên PostgreSQL đám mây
@app.on_event("startup")
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        balance INT DEFAULT 0
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        price INT NOT NULL,
        description TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS resources (
        id SERIAL PRIMARY KEY,
        product_id INT REFERENCES products(id),
        data TEXT NOT NULL,
        is_sold INT DEFAULT 0
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        product_id INT REFERENCES products(id),
        status TEXT DEFAULT 'PENDING',
        delivered_data TEXT
    )""")
    cursor.execute("SELECT COUNT(*) FROM products")
    if cursor.fetchone() == 0:
        cursor.execute("INSERT INTO products (name, price, description) VALUES ('Tài khoản Clone Facebook', 20000, 'Clone 50-100 bạn bè')")
        cursor.execute("INSERT INTO products (name, price, description) VALUES ('Key Phần Mềm VPN 1 Tháng', 50000, 'Key kích hoạt bản quyền 30 ngày')")
        cursor.execute("INSERT INTO resources (product_id, data) VALUES (1, 'clone_fb_user1|pass1|fa2')")
        cursor.execute("INSERT INTO resources (product_id, data) VALUES (1, 'clone_fb_user2|pass2|fa2')")
        cursor.execute("INSERT INTO resources (product_id, data) VALUES (2, 'VPN-KEY-XXXX-YYYY')")
    conn.commit()
    cursor.close()
    conn.close()

# ==================== KHU VỰC API BACKEND ====================
class PurchaseRequest(BaseModel):
    user_id: int
    product_id: int

class SePayWebhookData(BaseModel):
    id: int
    amountIn: int
    content: str

@app.get("/api/products")
def get_products():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT id, name, price, description FROM products")
    products = cursor.fetchall()
    cursor.close()
    conn.close()
    return products

@app.get("/api/user/{user_id}")
def get_user_balance(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id, balance) VALUES (%s, 0)", (user_id,))
        conn.commit()
        balance = 0
    else:
        balance = row[0]
    cursor.close()
    conn.close()
    return {"user_id": user_id, "balance": balance}

@app.get("/api/deposit-qr/{user_id}")
def get_deposit_qr(user_id: int, amount: int = 50000):
    memo = f"NAP_{user_id}"
    qr_url = f"https://vietqr.io{amount}&addInfo={memo}&accountName=NGUYEN%20VAN%20A"
    return {"qr_url": qr_url, "syntax": memo, "bank_name": "MB Bank", "account_number": "123456789"}

@app.post("/webhook/sepay")
def sepay_webhook(data: SePayWebhookData, x_api_key: Optional[str] = Header(None)):
    if x_api_key != WEBHOOK_API_KEY:
        raise HTTPException(status_code=404, detail="Not Found")
    content = data.content.upper()
    amount = data.amountIn
    if amount > 0 and "NAP_" in content:
        try:
            parts = content.split("NAP_")
            user_id = int("".join(filter(str.isdigit, parts)))
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
            if cursor.fetchone():
                cursor.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, user_id))
                conn.commit()
            cursor.close()
            conn.close()
            return {"status": "SUCCESS"}
        except Exception:
            return {"status": "ERROR"}
    return {"status": "SKIPPED"}

@app.post("/api/buy-product")
def buy_product_via_wallet(req: PurchaseRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT price FROM products WHERE id = %s FOR UPDATE", (req.product_id,))
        prod = cursor.fetchone()
        if not prod: return {"status": "FAILED", "message": "Sản phẩm không tồn tại."}
        price = prod[0]
        cursor.execute("SELECT balance FROM users WHERE user_id = %s FOR UPDATE", (req.user_id,))
        balance_row = cursor.fetchone()
        balance = balance_row[0] if balance_row else 0
        if balance < price:
            return {"status": "FAILED", "message": f"Số dư không đủ. Bạn cần nạp thêm {(price - balance):,}đ."}
        cursor.execute("SELECT id, data FROM resources WHERE product_id = %s AND is_sold = 0 LIMIT 1 FOR UPDATE", (req.product_id,))
        res_row = cursor.fetchone()
        if not res_row: return {"status": "FAILED", "message": "Sản phẩm này tạm hết hàng."}
        res_id, res_data = res_row
        cursor.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (price, req.user_id))
        cursor.execute("UPDATE resources SET is_sold = 1 WHERE id = %s", (res_id,))
        cursor.execute("INSERT INTO orders (user_id, product_id, status, delivered_data) VALUES (%s, %s, 'COMPLETED', %s)", (req.user_id, req.product_id, res_data))
        conn.commit()
        return {"status": "SUCCESS", "resource": res_data, "new_balance": balance - price}
    except Exception as e:
        conn.rollback()
        return {"status": "FAILED", "message": str(e)}
    finally:
        cursor.close()
        conn.close()

# ==================== KHU VỰC BOT TELEGRAM CHẠY NGẦM ====================
async def bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    # Tạo ví tự động cho khách khi bấm /start chat với bot
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (user_id, balance) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception:
        pass

    keyboard = [[InlineKeyboardButton("🛍️ Mở Cửa Hàng (Mini App)", web_app=WebAppInfo(url=MINI_APP_URL))]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        f"👋 Chào mừng {first_name} đến với **Kho Tài Nguyên MMO**!\n\n"
        f"📱 Cửa hàng Mini App đã được tích hợp trực tiếp. Bạn có thể mua sắm và quản lý ví tiền cực kỳ nhanh chóng.\n\n"
        f"💳 ID ví thành viên của bạn là: `{user_id}`\n\n"
        f"Hãy bấm nút **Mở Cửa Hàng** dưới đây để bắt đầu!"
    )
    await update.message.reply_text(text=welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

# Lệnh Admin nạp tiền nhanh ngay trong chat: /cong_tien ID Số_tiền
async def admin_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        target_user = int(context.args[0])
        amount = int(context.args[1])
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, target_user))
        conn.commit()
        cursor.close()
        conn.close()
        await update.message.reply_text(f"✅ Đã cộng **{amount:,} VND** vào ví thành viên `{target_user}`!")
    except Exception:
        await update.message.reply_text("⚠️ Cú pháp nạp tiền sai! Dạng chuẩn: `/cong_tien ID SO_TIEN`")

def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot_app = Application.builder().token(TOKEN).build()
    bot_app.add_handler(CommandHandler("start", bot_start))
    bot_app.add_handler(CommandHandler("cong_tien", admin_deposit))
    bot_app.run_polling(close_loop=False)

# Chạy bot trong một luồng riêng biệt để tránh nghẽn API của Web App
bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()
