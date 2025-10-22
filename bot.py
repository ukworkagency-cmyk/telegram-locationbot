import sqlite3
from datetime import datetime, date, timedelta, time
import pytz
from telegram import Update, Chat, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler

# --- KONFIG ---
TOKEN = "SENING_TOKENING_BU_YERDA"
TZ = pytz.timezone("Asia/Tashkent")
DB_PATH = "locations.db"

# --- DB FUNKSIYALAR ---
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

def is_allowed(chat_id: int, user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM allowed WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    result = cur.fetchone()
    conn.close()
    return bool(result)

def toggle_allowed(chat_id: int, user_id: int):
    if is_allowed(chat_id, user_id):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM allowed WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        conn.commit()
        conn.close()
    else:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("INSERT INTO allowed (chat_id, user_id) VALUES (?, ?)", (chat_id, user_id))
        conn.commit()
        conn.close()

# --- HISOBOT ---
async def send_report(app, chat_id: int, start_hm: str, end_hm: str):
    today = date.today()
    start_local = TZ.localize(datetime.combine(today, datetime.strptime(start_hm, "%H:%M").time()))
    end_local = TZ.localize(datetime.combine(today, datetime.strptime(end_hm, "%H:%M").time()))
    if end_local <= start_local:
        end_local += timedelta(days=1)
    start_utc = start_local.astimezone(pytz.UTC)
    end_utc = end_local.astimezone(pytz.UTC)

    members = get_members(chat_id)
    text = f"📅 Hisobot ({start_hm}–{end_hm}):\n\n"
    for uid, username, first_name, last_name in members:
        name = username or f"{first_name or ''} {last_name or ''}".strip() or f"user_{uid}"
        text += f"{name}\n"
    await app.bot.send_message(chat_id=chat_id, text=text)

async def daily_report_job(context: ContextTypes.DEFAULT_TYPE):
    for chat_id, _ in get_groups():
        await context.bot.send_message(chat_id=chat_id, text="📆 Kunlik hisobot ishga tushdi!")

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Salom! Bot ishlayapti ✅")

# --- INTERVALLAR ---
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

# --- MAIN ---
def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).job_queue().build()

    app.add_handler(CommandHandler("start", start))

    # Interval hisobotlar
    for start_hm, end_hm, report_time in INTERVALS:
        app.job_queue.run_daily(make_job(start_hm, end_hm), report_time)

    # Kunlik hisobot
    app.job_queue.run_daily(daily_report_job, time(19, 0))

    print("🤖 Bot ishga tushdi (Render.com)")
    app.run_polling()

if __name__ == "__main__":
    main()
