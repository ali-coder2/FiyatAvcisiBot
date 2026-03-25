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

# ---------- SAFE MARKDOWN ----------
def escape_md(text: str) -> str:
    if not text:
        return ""
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return ''.join(['\\' + c if c in escape_chars else c for c in str(text)])

# ---------- STATES ----------
class SearchStates(StatesGroup):
    waiting_query = State()
    waiting_target_price = State()

class AdminStates(StatesGroup):
    waiting_ref = State()
    waiting_ad = State()

# ---------- DB ----------
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS premium (user_id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS favorites (user_id INTEGER, link TEXT, title TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS alerts (user_id INTEGER, link TEXT, target REAL)")
        await db.commit()

# ---------- HELPERS ----------
def gen_ref(prefix, user_id):
    return f"{prefix}-{user_id}-" + ''.join(random.choices(string.ascii_uppercase, k=5))

async def is_premium(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT 1 FROM premium WHERE user_id=?", (user_id,)) as c:
            return await c.fetchone() is not None

async def set_premium(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO premium VALUES (?)", (user_id,))
        await db.commit()

async def search_products(query):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: GoogleSearch({
        "api_key": SERPAPI_KEY,
        "engine": "google_shopping",
        "q": query,
        "hl": "tr",
        "gl": "tr",
        "num": 10
    }).get_dict())

# ---------- UI ----------
def menu_kb(is_prem, is_admin):
    kb = [
        [InlineKeyboardButton(text="🔍 Ara", callback_data="search")],
        [InlineKeyboardButton(text="⭐ Favoriler", callback_data="fav")]
    ]
    if not is_prem:
        kb.append([InlineKeyboardButton(text="💰 Reklam Kaldır", callback_data="premium")])
    else:
        kb.append([InlineKeyboardButton(text="✅ Premium", callback_data="noop")])
    if is_admin:
        kb.append([InlineKeyboardButton(text="📢 Reklam Gönder", callback_data="send_ad")])
        kb.append([InlineKeyboardButton(text="💳 Ödeme Onayla", callback_data="approve")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def product_kb(i, total):
    nav = []
    if i > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data="prev"))
    if i < total-1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data="next"))

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Favori", callback_data=f"fav_add:{i}")],
        [InlineKeyboardButton(text="🔔 Takip", callback_data=f"track:{i}")],
        nav,
        [InlineKeyboardButton(text="🔙 Menü", callback_data="menu")]
    ])

# ---------- SHOW PRODUCT ----------
async def show_product(msg, user_id):
    cache = RESULTS_CACHE.get(user_id)
    if not cache:
        return

    i = cache["i"]
    product = cache["data"][i]

    title = escape_md(product.get("title"))
    price = product.get("price", "Yok")
    source = escape_md(product.get("source", ""))

    text = f"**{title}**\n💰 {price}\n🏪 {source}"

    try:
        await msg.edit_text(text, reply_markup=product_kb(i, len(cache["data"])), parse_mode="Markdown")
    except:
        await msg.answer(text, reply_markup=product_kb(i, len(cache["data"])), parse_mode="Markdown")

# ---------- START ----------
@dp.message(Command("start"))
async def start(m: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
        await db.commit()

    prem = await is_premium(m.from_user.id)

    await m.answer(
        "Hoş geldin!",
        reply_markup=menu_kb(prem, m.from_user.id == ADMIN_ID)
    )

# ---------- SEARCH ----------
@dp.callback_query(F.data == "search")
async def search(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Ürün yaz:")
    await state.set_state(SearchStates.waiting_query)
    await cb.answer()

@dp.message(SearchStates.waiting_query)
async def do_search(m: Message, state: FSMContext):
    res = await search_products(m.text)
    items = res.get("shopping_results", [])

    RESULTS_CACHE[m.from_user.id] = {"data": items, "i": 0}

    await show_product(m, m.from_user.id)
    await state.clear()

# ---------- NAV ----------
@dp.callback_query(F.data.in_(["next", "prev"]))
async def nav(cb: CallbackQuery):
    cache = RESULTS_CACHE.get(cb.from_user.id)
    if not cache:
        return

    if cb.data == "next":
        cache["i"] += 1
    else:
        cache["i"] -= 1

    await show_product(cb.message, cb.from_user.id)
    await cb.answer()

# ---------- MENU BACK ----------
@dp.callback_query(F.data == "menu")
async def menu(cb: CallbackQuery):
    prem = await is_premium(cb.from_user.id)
    await cb.message.edit_text("Menü", reply_markup=menu_kb(prem, cb.from_user.id == ADMIN_ID))
    await cb.answer()

# ---------- PREMIUM ----------
@dp.callback_query(F.data == "premium")
async def premium(cb: CallbackQuery):
    ref = gen_ref("PREM", cb.from_user.id)
    await cb.message.edit_text(
        f"{PREMIUM_PRICE} TL\nIBAN: {IBAN}\nKod: {ref}"
    )
    await cb.answer()

# ---------- APPROVE ----------
@dp.callback_query(F.data == "approve")
async def approve(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer("Ref kod gir:")
    await state.set_state(AdminStates.waiting_ref)
    await cb.answer()

@dp.message(AdminStates.waiting_ref)
async def do_approve(m: Message, state: FSMContext):
    ref = m.text
    if ref.startswith("PREM-"):
        user_id = int(ref.split("-")[1])
        await set_premium(user_id)
        await m.answer("Onaylandı")
    await state.clear()

# ---------- REKLAM ----------
@dp.callback_query(F.data == "send_ad")
async def send_ad(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer("Reklam yaz:")
    await state.set_state(AdminStates.waiting_ad)
    await cb.answer()

@dp.message(AdminStates.waiting_ad)
async def broadcast(m: Message, state: FSMContext):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as c:
            users = await c.fetchall()

    for (uid,) in users:
        if not await is_premium(uid):
            try:
                await bot.send_message(uid, f"📢 {m.text}")
            except:
                pass

    await m.answer("Gönderildi")
    await state.clear()

# ---------- MAIN ----------
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())