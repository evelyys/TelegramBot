
import asyncio
import logging
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from dotenv import load_dotenv
import os

# ================== CONFIG ==================
load_dotenv()

API_TOKEN = os.getenv("TOKEN")

bot = Bot(token=API_TOKEN)
BOOKS_FOLDER = "books"
DB_PATH = "library.db"
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)


waiting_for_book = set()
pending_books = {}

# ================== DATABASE ==================
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    last_quote_date TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    book_title TEXT,
    author TEXT,
    file_path TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL
)
""")

# Инициализация цитат
cursor.execute("SELECT COUNT(*) FROM quotes")
if cursor.fetchone()[0] == 0:
    quotes = [
        '"Чтение - лучшее учение". - А.С. Пушкин',
        '"Книга - это устройство для разжигания воображения". - А. Беннетт',
        '"Человек перестаёт мыслить, когда перестаёт читать". - Д. Дидро',
        '"Книги - корабли мысли". - Ф. Бэкон',
        '"Тот, кто читает книги, проживает тысячи жизней". - Дж. Мартин',
        '"Силу подлости и злобы одолет дух добра". - Б. Пастернак',
        '"В человеке должно быть все прекрасно: и лицо, и одежда, и мылсли". - Чехов'
    ]
    for q in quotes:
        cursor.execute("INSERT INTO quotes (text) VALUES (?)", (q,))
    conn.commit()

# ================== UI ==================
def main_menu():
    kb = ReplyKeyboardBuilder()
    kb.add(KeyboardButton(text="📚 Найти книгу"))
    kb.add(KeyboardButton(text="🧠 Цитата дня"))
    kb.add(KeyboardButton(text="📖 Моя библиотека"))
    kb.adjust(1)
    return kb.as_markup(resize_keyboard=True)

def add_book_inline_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ В библиотеку", callback_data="add_book"),
            InlineKeyboardButton(text="❌ Не добавлять", callback_data="skip_book")
        ]
    ])

# ================== UTILS ==================
def find_local_book_file(title: str):
    if not os.path.exists(BOOKS_FOLDER):
        return None
    title = title.lower()
    for file in os.listdir(BOOKS_FOLDER):
        name, ext = os.path.splitext(file)
        if ext.lower() not in [".pdf", ".epub", ".fb2", ".txt"]:
            continue
        if title in name.lower():
            return os.path.join(BOOKS_FOLDER, file)
    return None

def can_send_quote(user_id):
    today = datetime.utcnow().date().isoformat()
    cursor.execute("SELECT last_quote_date FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute(
            "INSERT INTO users (user_id, last_quote_date) VALUES (?, ?)",
            (user_id, today)
        )
        conn.commit()
        return True
    if row[0] != today:
        cursor.execute(
            "UPDATE users SET last_quote_date=? WHERE user_id=?",
            (today, user_id)
        )
        conn.commit()
        return True
    return False

def get_quote():
    cursor.execute("SELECT text FROM quotes ORDER BY RANDOM() LIMIT 1")
    return cursor.fetchone()[0]

# ================== HANDLERS ==================
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "Привет!\n"
        "\n"
        "Бот умеет:\n"
        "\n"
        "- искать книги по названию\n- отправлять цитату дня\n- сохранять найденые книги в библиотеку",
        reply_markup=main_menu()
    )

@dp.message(lambda m: m.text == "📚 Найти книгу")
async def ask_book(message: types.Message):
    waiting_for_book.add(message.from_user.id)
    await message.answer("✍️ Введите название книги:")

@dp.message(lambda m: m.text == "🧠 Цитата дня")
async def quote(message: types.Message):
    if can_send_quote(message.from_user.id):
        await message.answer(f"🧠 {get_quote()}")
    else:
        await message.answer("Вы уже получали цитату сегодня 🙂")

@dp.message(lambda m: m.text == "📖 Моя библиотека")
async def library(message: types.Message):
    cursor.execute(
        "SELECT id, book_title, author, file_path FROM library WHERE user_id=?",
        (message.from_user.id,)
    )
    books = cursor.fetchall()
    if not books:
        await message.answer("Ваша библиотека пуста.")
        return
    text = "📖 Ваша библиотека:\n\n"
    kb = []
    for i, (bid, title, author, file) in enumerate(books, 1):
        text += f"{i}. {title}\n"
        row = [
            InlineKeyboardButton(text="📥 Скачать", callback_data=f"download_{bid}"),
            InlineKeyboardButton(text="❌ Удалить", callback_data=f"delete_{bid}")
        ]
        kb.append(row)
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.message()
async def search_book(message: types.Message):
    user_id = message.from_user.id
    query = message.text.strip().lower()
    local_file = find_local_book_file(query)
    if local_file:
        title = os.path.splitext(os.path.basename(local_file))[0]
        description = "Книга найдена и готова для скачивания.\nНажмите: ➕ В библиотеку"
        pending_books[user_id] = {
            "book": {
                "title": title,
                "authors": "",
                "description": description,
                "source": "Локальная библиотека"
            },
            "file": local_file
        }
        text = f"📚 *{title}*\n\n📝 {description}"
        await message.answer(text, parse_mode="Markdown", reply_markup=add_book_inline_kb())
    else:
        await message.answer("Книга не найдена 😔")


@dp.callback_query(lambda c: c.data == "add_book")
async def add_book_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in pending_books:
        await callback.answer("Книга не найдена.")
        return
    data = pending_books.pop(user_id)
    book = data["book"]
    file_path = data["file"]
    cursor.execute(
        "SELECT id FROM library WHERE user_id=? AND book_title=?",
        (user_id, book["title"])
    )
    if cursor.fetchone():
        await callback.answer("Эта книга уже есть в вашей библиотеке 📖")
        return
    cursor.execute(
        "INSERT INTO library (user_id, book_title, author, file_path) VALUES (?, ?, ?, ?)",
        (user_id, book["title"], book["authors"], file_path)
    )
    conn.commit()
    await callback.message.edit_text(f"✅ Книга *{book['title']}* добавлена в библиотеку!", parse_mode="Markdown")
    if file_path and os.path.exists(file_path):
        await callback.message.answer_document(types.FSInputFile(file_path), caption=f"📎 {book['title']}")

@dp.callback_query(lambda c: c.data == "skip_book")
async def skip(cb: types.CallbackQuery):
    pending_books.pop(cb.from_user.id, None)
    await cb.message.edit_text("❌ Книга не добавлена.")

@dp.callback_query(lambda c: c.data.startswith("delete_"))
async def delete(cb: types.CallbackQuery):
    bid = int(cb.data.split("_")[1])
    cursor.execute("DELETE FROM library WHERE id=? AND user_id=?", (bid, cb.from_user.id))
    conn.commit()
    await cb.answer("Удалено")

@dp.callback_query(lambda c: c.data.startswith("download_"))
async def download(cb: types.CallbackQuery):
    bid = int(cb.data.split("_")[1])
    cursor.execute("SELECT file_path FROM library WHERE id=? AND user_id=?", (bid, cb.from_user.id))
    row = cursor.fetchone()
    if not row or not row[0]:
        await cb.answer("Файл недоступен")
        return
    await cb.message.answer_document(types.FSInputFile(row[0]))


async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())