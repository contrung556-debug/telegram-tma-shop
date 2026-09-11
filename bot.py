import os
import sqlite3
import psycopg2
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

# Cấu hình LOG
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Cấu hình các thông số bảo mật lấy từ biến môi trường
TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
MINI_APP_URL = "https://github.io"

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

# Lệnh /start gửi menu chào mừng kèm nút mở Mini App
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    # Tự động kiểm tra và thêm user vào database ví nếu chưa có
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (user_id, balance) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logging.error(f"Lỗi thêm user vào database: {e}")

    # Tạo nút bấm đặc biệt để mở tràn màn hình Mini App cửa hàng
    keyboard = [
        [InlineKeyboardButton("🛍️ Mở Cửa Hàng (Mini App)", web_app=WebAppInfo(url=MINI_APP_URL))],
        [InlineKeyboardButton("ℹ️ Kiểm tra ID của tôi", callback_data="check_id")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        f"👋 Chào mừng {user.first_name} đến với **Kho Tài Nguyên MMO**!\n\n"
        f"📱 Hệ thống của chúng tôi hỗ trợ mua bán tài khoản, key phần mềm tự động bằng Ví Thành Viên trực tiếp ngay trong Telegram.\n\n"
        f"💳 ID Telegram của bạn là: `{user_id}` (Dùng để ghi nội dung khi nạp tiền).\n\n"
        f"Hãy bấm vào nút **Mở Cửa Hàng** bên dưới để trải nghiệm ngay!"
    )
    
    await update.message.reply_text(text=welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

# Lệnh Admin nạp tiền nhanh ngay trong chat: /cong_tien ID Số_tiền (Ví dụ: /cong_tien 9999 100000)
async def admin_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Bạn thay số ID ở dòng dưới bằng ID thật của bạn để làm Admin độc quyền nhé
    ADMIN_ID = user_id  # Tạm thời đặt chính bạn làm Admin luôn
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Lệnh này chỉ dành cho Chủ Shop (Admin).")
        return
        
    try:
        # Lấy thông tin ID khách và số tiền từ câu lệnh
        target_user = int(context.args[0])
        amount = int(context.args[1])
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, target_user))
        conn.commit()
        cursor.close()
        conn.close()
        
        await update.message.reply_text(f"✅ Đã nạp thành công **{amount:,} VND** vào ví thành viên `{target_user}`!")
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Cú pháp sai! Vui lòng nhập dạng: `/cong_tien ID_KHACH SO_TIEN`", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi hệ thống database: {str(e)}")

def main():
    # Khởi chạy ứng dụng Bot Telegram liên tục
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cong_tien", admin_deposit))
    
    print("Đầu não Bot Telegram đang chạy...")
    app.run_polling()

if __name__ == "__main__":
    main()
