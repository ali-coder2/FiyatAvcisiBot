import asyncio
import json
import hashlib
import random
import string
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
def escape_md(text: str) -> str:
    if not text:
        return ""
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return ''.join(['\\' + c if c in escape_chars else c for c in str(text)])
from serpapi import GoogleSearch
from dotenv import load_dotenv
import os
import aiosqlite

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
IBAN = os.getenv("IBAN")

PREMIUM_PRICE = 45
AD_PRICE = 85
BOT_NAME = "FiyatAvcısıBot"
MY_TELEGRAM = "@Vortex2000"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DB_NAME = "shopping_bot.db"

RESULTS_CACHE = {}

class SearchStates(StatesGroup):
    waiting_query = State()
    waiting_min_price = State()
    waiting_max_price = State()
    waiting_target_price = State()

class AdminStates(StatesGroup):
    waiting_ref_code = State()
    waiting_ad_text = State()

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS searches (
            query_hash TEXT PRIMARY KEY,
            results_json TEXT,
            created_at TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER,
            title TEXT,
            price REAL,
            link TEXT,
            thumbnail TEXT,
            source TEXT,
            added_at TEXT,
            PRIMARY KEY (user_id, link)
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS premium_users (
            user_id INTEGER PRIMARY KEY,
            paid_at TEXT,
            ref_code TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS price_alerts (
            user_id INTEGER,
            link TEXT,
            target_price REAL
        )
        """)
        await db.commit()

async def save_user(user_id, username=None, first_name=None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?)
        """, (user_id, username, first_name, datetime.now().isoformat()))
        await db.commit()

async def is_premium(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT 1 FROM premium_users WHERE user_id=?", (user_id,)) as c:
            return await c.fetchone() is not None

async def set_premium(user_id, ref):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO premium_users VALUES (?, ?, ?)",
                         (user_id, datetime.now().isoformat(), ref))
        await db.commit()

def generate_ref_code(prefix, user_id):
    return f"{prefix}-{user_id}-" + ''.join(random.choices(string.ascii_uppercase, k=5))

def get_query_hash(query, min_p, max_p, sort):
    return hashlib.md5(f"{query}{min_p}{max_p}{sort}".encode()).hexdigest()

async def search_products(query, min_price=None, max_price=None, sort_type="relevance"):
    params = {
        "api_key": SERPAPI_KEY,
        "engine": "google_shopping",
        "q": query,
        "gl": "tr",
        "hl": "tr",
        "num": 10
    }
    if min_price:
        params["min_price"] = min_price
    if max_price:
        params["max_price"] = max_price

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, lambda: GoogleSearch(params).get_dict())
    return results

def pagination_keyboard(index, total):
    buttons = [
        [InlineKeyboardButton(text="⭐ Favori", callback_data=f"add_fav:{index}")],
        [InlineKeyboardButton(text="🔍 Detay", callback_data=f"detail:{index}")],
        [InlineKeyboardButton(text="🔔 Takip", callback_data=f"track:{index}")]
    ]

    nav = []
    if index > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data="prev"))
    if index < total - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data="next"))

    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton(text="🔙 Menü", callback_data="back_to_menu")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def show_product(user_id):
    cache = RESULTS_CACHE.get(user_id)
    if not cache:
        return

    if datetime.now() - cache["time"] > timedelta(minutes=10):
        RESULTS_CACHE.pop(user_id)
        return

    index = cache["page"]
    product = cache["data"][index]

    title = escape_md(product.get("title", "Yok"))
    price = product.get("price", "Yok")
    source = escape_md(product.get("source", "Yok"))
    thumbnail = product.get("thumbnail")

    caption = f"**{title}**\n💰 {price}\n🏪 {source}"

    kb = pagination_keyboard(index, len(cache["data"]))

    if thumbnail:
        await bot.send_photo(user_id, thumbnail, caption=caption, parse_mode="Markdown", reply_markup=kb)
    else:
        await bot.send_message(user_id, caption, parse_mode="Markdown", reply_markup=kb)

@dp.message(Command("start"))
async def start(message: Message):
    await save_user(message.from_user.id, message.from_user.username, message.from_user.first_name)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Ara", callback_data="search")],
        [InlineKeyboardButton(text="⭐ Favoriler", callback_data="fav")],
        [InlineKeyboardButton(text="🔥 Trend", callback_data="trend")]
    ])

    await message.answer("Hoş geldin!", reply_markup=kb)

@dp.callback_query(F.data == "search")
async def search(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Ürün adı gir:")
    await state.set_state(SearchStates.waiting_query)

@dp.message(SearchStates.waiting_query)
async def get_query(message: Message, state: FSMContext):
    await state.update_data(query=message.text)
    data = await state.get_data()

    results = await search_products(data["query"])
    shopping = results.get("shopping_results", [])

    if not shopping:
        await message.answer("Sonuç yok")
        return

    RESULTS_CACHE[message.from_user.id] = {
        "data": shopping,
        "page": 0,
        "time": datetime.now()
    }

    await show_product(message.from_user.id)
    await state.clear()

@dp.callback_query(F.data.in_(["next", "prev"]))
async def nav(callback: CallbackQuery):
    cache = RESULTS_CACHE.get(callback.from_user.id)
    if not cache:
        return

    if callback.data == "next":
        cache["page"] += 1
    else:
        cache["page"] -= 1

    await show_product(callback.from_user.id)

@dp.callback_query(F.data.startswith("add_fav:"))
async def add_fav(callback: CallbackQuery):
    idx = int(callback.data.split(":")[1])
    cache = RESULTS_CACHE.get(callback.from_user.id)
    product = cache["data"][idx]

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        INSERT OR IGNORE INTO favorites VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            callback.from_user.id,
            product.get("title"),
            product.get("extracted_price"),
            product.get("link"),
            product.get("thumbnail"),
            product.get("source"),
            datetime.now().isoformat()
        ))
        await db.commit()

    await callback.answer("Eklendi")

@dp.callback_query(F.data == "fav")
async def fav(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT title, price FROM favorites WHERE user_id=?", (callback.from_user.id,)) as c:
            rows = await c.fetchall()

    if not rows:
        await callback.message.answer("Boş")
        return

    text = "\n".join([f"{r[0]} - {r[1]} TL" for r in rows])
    await callback.message.answer(text)

@dp.callback_query(F.data.startswith("detail:"))
async def detail(callback: CallbackQuery):
    idx = int(callback.data.split(":")[1])
    product = RESULTS_CACHE[callback.from_user.id]["data"][idx]

    text = f"{product.get('title')}\n{product.get('price')}\n{product.get('link')}"
    await callback.message.answer(text)

@dp.callback_query(F.data.startswith("track:"))
async def track(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[1])
    product = RESULTS_CACHE[callback.from_user.id]["data"][idx]

    await state.update_data(track_product=product)
    await callback.message.answer("Hedef fiyat gir:")
    await state.set_state(SearchStates.waiting_target_price)

@dp.message(SearchStates.waiting_target_price)
async def set_target(message: Message, state: FSMContext):
    try:
        target = float(message.text)
    except:
        await message.answer("Sayı gir")
        return

    data = await state.get_data()
    product = data["track_product"]

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO price_alerts VALUES (?, ?, ?)",
                         (message.from_user.id, product.get("link"), target))
        await db.commit()

    await message.answer("Takip başlatıldı")
    await state.clear()

async def price_checker():
    while True:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT user_id, link, target_price FROM price_alerts") as c:
                alerts = await c.fetchall()

        for user_id, link, target in alerts:
            results = await search_products(link)
            items = results.get("shopping_results", [])

            for item in items:
                price = item.get("extracted_price")
                if price and price <= target:
                    await bot.send_message(user_id, f"🔥 Fiyat düştü!\n{item.get('title')} - {price} TL")

        await asyncio.sleep(3600)

async def main():
    await init_db()
    asyncio.create_task(price_checker())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())