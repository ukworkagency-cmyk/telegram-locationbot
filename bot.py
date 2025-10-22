import os
import sqlite3
from datetime import datetime, date, timedelta, time
import pytz
from telegram import Update, Chat, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackQueryHandler
)
from keep_alive import keep_alive

# --- KONFIG ---
TOKEN = os.getenv("TOKEN")  # Render.com da Environment Variable orqali beriladi
TZ = pytz.timezone("Asia/Tashkent")
DB_PATH = "locations.db"

# --- DB funksiyalar ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS members (
        chat_id INTEGER,
        user_id INTEGER,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        PRIMARY KEY (chat_id, user_id)
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS locations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        user_id INTEGER,
        timestamp_utc TEXT,
        latitude REAL,
        longitude REAL
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS groupinfo (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER UNIQUE,
        title TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS allowed (
        chat_id INTEGER,
        user_id INTEGER,
        PRIMARY KEY(chat_id, user_id)
    )""")
    conn.commit()
    conn.close()

def register_member(chat_id: int, user):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO members (chat_id, user_id, username, first_name, last_name)
        VALUES (?, ?, ?, ?, ?)
    """, (chat_id, user.id, user.username, user.first_name, user.last_name))
    conn.commit()
    conn.close()

def save_location(chat_id: int, user_id: int, latitude: float, longitude: float, ts_utc: datetime):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO locations (chat_id, user_id, timestamp_utc, latitude, longitude)
        VALUES (?, ?, ?, ?, ?)
    """, (chat_id, user_id, ts_utc.isoformat(), latitude, longitude))
    conn.commit()
    conn.close()

def save_group(chat_id: int, title: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO groupinfo (chat_id, title) VALUES (?, ?)", (chat_id, title))
    conn.commit()
    conn.close()

def get_groups():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT chat_id, title FROM groupinfo")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_members(chat_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, first_name, last_name FROM members WHERE chat_id=?", (chat_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_locations_in_interval(chat_id: int, ts_from_utc: datetime, ts_to_utc: datetime):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT l.user_id, COUNT(*) 
        FROM locations l
        JOIN allowed a ON l.chat_id=a.chat_id AND l.user_id=a.user_id
        WHERE l.chat_id=? AND l.timestamp_utc BETWEEN ? AND ?
        GROUP BY l.user_id
    """, (chat_id, ts_from_utc.isoformat(), ts_to_utc.isoformat()))
    rows = cur.fetchall()
    conn.close()
    return rows

def is_allowed(chat_id: int, user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM allowed WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    result = cur.fetchone()
    conn.close()
    return bool(result)

def toggle_allowed(chat_id: int, user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if is_allowed(chat_id, user_id):
        cur.execute("DELETE FROM allowed WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    else:
        cur.execute("INSERT INTO allowed (chat_id, user_id) VALUES (?, ?)", (chat_id, user_id))
    conn.commit()
    conn.close()

# --- Hisobot funksiyalar ---
async def send_report(app, chat_id: int, start_hm: str, end_hm: str):
    today = date.today()
    start_local = TZ.localize(datetime.combine(today, datetime.strptime(start_hm, "%H:%M").time()))
    end_local = TZ.localize(datetime.combine(today, datetime.strptime(end_hm, "%H:%M").time()))
    if end_local <= start_local:
        end_local += timedelta(days=1)
    start_utc = start_local.astimezone(pytz.UTC)
    end_utc = end_local.astimezone(pytz.UTC)

    members = [m for m in get_members(chat_id) if is_allowed(chat_id, m[0])]
    sent_counts = dict(get_locations_in_interval(chat_id, start_utc, end_utc))

    text = f"📅 Hisobot ({start_hm}–{end_hm}):\n\n"
    for uid, username, first_name, last_name in members:
        name = username or f"{first_name or ''} {last_name or ''}".strip() or f"user_{uid}"
        count = sent_counts.get(uid, 0)
        text += f"{name}: {count} ta lokatsiya\n"
    await app.bot.send_message(chat_id=chat_id, text=text)

async def daily_report_job(context: ContextTypes.DEFAULT_TYPE):
    for chat_id, _ in get_groups():
        today = date.today()
        start_utc = TZ.localize(datetime.combine(today, time(0,0))).astimezone(pytz.UTC)
        end_utc = TZ.localize(datetime.combine(today, time(23,59,59))).astimezone(pytz.UTC)
        members = [m for m in get_members(chat_id) if is_allowed(chat_id, m[0])]
        sent_counts = dict(get_locations_in_interval(chat_id, start_utc, end_utc))
        text = f"📆 Kunlik hisobot ({today}):\n\n"
        for uid, username, first_name, last_name in members:
            name = username or f"{first_name or ''} {last_name or ''}".strip() or f"user_{uid}"
            count = sent_counts.get(uid, 0)
            text += f"{name}: {count} ta lokatsiya\n"
        await context.bot.send_message(chat_id=chat_id, text=text)

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Salom! Men guruh lokatsiya kuzatuvchi botiman.\n"
        "Guruhni ro‘yxatga olish: /setgroup\n"
        "Qo‘l hisobot: /report HH:MM HH:MM\n"
        "Admin uchun ruxsat berish: /allow"
    )

async def setgroup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    member = await chat.get_member(user.id)
    if member.status not in ("administrator", "creator"):
        await update.message.reply_text("❌ Faqat admin/owner ishlata oladi.")
        return
    if chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await update.message.reply_text("Bu buyruq faqat guruhda ishlaydi.")
        return
    save_group(chat.id, chat.title or "No title")
    await update.message.reply_text(f"✅ Guruh ro‘yxatga olindi! Chat ID: `{chat.id}`", parse_mode="Markdown")

async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    member = await chat.get_member(user.id)
    if member.status not in ("administrator", "creator"):
        await update.message.reply_text("❌ Faqat admin/owner ishlata oladi.")
        return
    if len(context.args) != 2:
        await update.message.reply_text("❌ Format: /report 08:00 09:30")
        return
    start_hm, end_hm = context.args
    await send_report(context.application, chat.id, start_hm, end_hm)

async def any_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        return
    register_member(chat.id, user)
    if update.message and update.message.location:
        if not is_allowed(chat.id, user.id):
            await update.message.reply_text("❌ Siz lokatsiya yuborish uchun ruxsat olmagansiz.")
            return
        ts_utc = update.message.date.replace(tzinfo=pytz.UTC)
        save_location(chat.id, user.id, update.message.location.latitude, update.message.location.longitude, ts_utc)
        await update.message.reply_text("📍 Lokatsiya qabul qilindi!")

async def allow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    member = await chat.get_member(user.id)
    if member.status not in ("administrator", "creator"):
        await update.message.reply_text("❌ Faqat admin/owner ishlata oladi.")
        return
    members = get_members(chat.id)
    keyboard = []
    for uid, username, first_name, last_name in members:
        name = username or f"{first_name or ''} {last_name or ''}".strip() or f"user_{uid}"
        mark = "✅" if is_allowed(chat.id, uid) else ""
        keyboard.append([InlineKeyboardButton(f"{name} {mark}", callback_data=f"allow_{uid}")])
    await update.message.reply_text("✅ Ruxsat berish uchun tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))

async def allow_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    chat = query.message.chat
    member = await chat.get_member(user.id)
    if member.status not in ("administrator", "creator"):
        await query.answer("❌ Faqat admin/owner ishlata oladi.", show_alert=True)
        return
    data = query.data
    if data.startswith("allow_"):
        uid = int(data.split("_")[1])
        toggle_allowed(chat.id, uid)
        members = get_members(chat.id)
        keyboard = []
        for m_uid, username, first_name, last_name in members:
            name = username or f"{first_name or ''} {last_name or ''}".strip() or f"user_{m_uid}"
            mark = "✅" if is_allowed(chat.id, m_uid) else ""
            keyboard.append([InlineKeyboardButton(f"{name} {mark}", callback_data=f"allow_{m_uid}")])
        await query.edit_message_text("✅ Ruxsat berish uchun tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- Hisobot vaqtlarini belgilang ---
INTERVALS = [
    ("08:00", "09:30", time(9, 30)),
    ("12:00", "14:00", time(14, 0)),
    ("15:00", "16:30", time(16, 30)),
]

def make_job(start_hm, end_hm):
    async def job(context: ContextTypes.DEFAULT_TYPE):
        for chat_id, _ in get_groups():
            await send_report(context.application, chat_id, start_hm, end_hm)
    return job

def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setgroup", setgroup_cmd))
    app.add_handler(CommandHandler("report", report_cmd))
    app.add_handler(CommandHandler("allow", allow_cmd))
    app.add_handler(MessageHandler(filters.ALL, any_message_handler))
    app.add_handler(CallbackQueryHandler(allow_callback, pattern="^allow_"))

    for start_hm, end_hm, report_time in INTERVALS:
        app.job_queue.run_daily(make_job(start_hm, end_hm), report_time)

    app.job_queue.run_daily(daily_report_job, time(19,0))
    print("🤖 Bot ishga tushdi...")
    app.run_polling()

if __name__ == "__main__":
    keep_alive()
    main()
