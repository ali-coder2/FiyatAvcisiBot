import asyncio
import os
import random
import string
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from serpapi import GoogleSearch
import aiosqlite
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
IBAN = os.getenv("IBAN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
DB = "db.sqlite"
CACHE = {}

# ---------- STATES ----------
class States(StatesGroup):
    query = State()
    min_price = State()
    max_price = State()

# ---------- DB ----------
async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS premium (id INTEGER PRIMARY KEY)")
        await db.commit()

# ---------- HELPERS ----------
def ref_code(uid):
    return f"PREM-{uid}-" + ''.join(random.choices(string.ascii_uppercase, k=5))

async def is_premium(uid):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT 1 FROM premium WHERE id=?", (uid,)) as c:
            return await c.fetchone() is not None

async def search(q, min_p=None, max_p=None):
    params = {
        "api_key": SERPAPI_KEY,
        "engine": "google_shopping",
        "q": q,
        "hl": "tr",
        "gl": "tr",
        "num": 10
    }
    if min_p is not None:
        params["min_price"] = min_p
    if max_p is not None:
        params["max_price"] = max_p
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: GoogleSearch(params).get_dict())

# ---------- KEYBOARDS ----------
def menu_kb(prem, admin):
    kb = [
        [InlineKeyboardButton("🔍 Ara", callback_data="search")],
    ]
    if not prem:
        kb.append([InlineKeyboardButton("💰 Reklam Kaldır", callback_data="premium")])
    else:
        kb.append([InlineKeyboardButton("✅ Premium", callback_data="noop")])
    if admin:
        kb.append([InlineKeyboardButton("📢 Reklam", callback_data="ad")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton("🔙 Menü", callback_data="menu")]])

def budget_choice_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("Bütçe Belirle", callback_data="budget")],
        [InlineKeyboardButton("Filtresiz", callback_data="nofilter")]
    ])

def product_kb(i, total, link):
    nav = []
    if i > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data="prev"))
    if i < total-1:
        nav.append(InlineKeyboardButton("➡️", callback_data="next"))
    kb = [[InlineKeyboardButton("🔗 Ürüne Git", url=link)]]
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("🔙 Menü", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ---------- START ----------
@dp.message(Command("start"))
async def start(m: Message):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
        await db.commit()
    prem = await is_premium(m.from_user.id)
    await m.answer("Hoş geldin!", reply_markup=menu_kb(prem, m.from_user.id == ADMIN_ID))

# ---------- MENU ----------
@dp.callback_query(F.data == "menu")
async def menu(cb: CallbackQuery):
    prem = await is_premium(cb.from_user.id)
    await cb.message.edit_text("Menü", reply_markup=menu_kb(prem, cb.from_user.id == ADMIN_ID))
    await cb.answer()

# ---------- SEARCH FLOW ----------
@dp.callback_query(F.data == "search")
async def search_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Ürün adı yaz:")
    await state.set_state(States.query)
    await cb.answer()

@dp.message(States.query)
async def set_query(m: Message, state: FSMContext):
    await state.update_data(q=m.text)
    await m.answer("Seçim yap:", reply_markup=budget_choice_kb())

@dp.callback_query(F.data.in_(["budget", "nofilter"]))
async def search_type(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    query = data.get("q")
    if not query:
        await cb.message.edit_text("Önce ürün adı yazmalısınız.")
        await state.set_state(States.query)
        await cb.answer()
        return

    if cb.data == "budget":
        await cb.message.edit_text("Minimum fiyat (TL) gir:")
        await state.set_state(States.min_price)
    else:
        res = await search(query)
        items = res.get("shopping_results", [])
        if not items:
            await cb.message.edit_text("Aradığınız ürün bulunamadı.", reply_markup=back_kb())
            await cb.answer()
            return
        CACHE[cb.from_user.id] = {"data": items, "i": 0}
        item = items[0]
        text = f"**{item.get('title')}**\n💰 {item.get('price')}\n🔗 {item.get('link')}"
        await cb.message.edit_text(text, reply_markup=product_kb(0, len(items), item.get("link")), parse_mode="Markdown")
        await state.clear()
    await cb.answer()

@dp.message(States.min_price)
async def set_min_price(m: Message, state: FSMContext):
    try:
        val = float(m.text)
    except:
        await m.answer("Sayı gir")
        return
    await state.update_data(min=val)
    await m.answer("Maksimum fiyat (TL) gir:")
    await state.set_state(States.max_price)

@dp.message(States.max_price)
async def set_max_price(m: Message, state: FSMContext):
    try:
        val = float(m.text)
    except:
        await m.answer("Sayı gir")
        return
    data = await state.get_data()
    min_val = data.get("min")
    query = data.get("q")
    res = await search(query, min_val, val)
    items = res.get("shopping_results", [])
    if not items:
        await m.answer("Sonuç yok")
        return
    CACHE[m.from_user.id] = {"data": items, "i": 0}
    item = items[0]
    text = f"**{item.get('title')}**\n💰 {item.get('price')}\n🔗 {item.get('link')}"
    await m.answer(text, reply_markup=product_kb(0, len(items), item.get("link")), parse_mode="Markdown")
    await state.clear()

# ---------- NAV ----------
@dp.callback_query(F.data.in_(["next", "prev"]))
async def nav(cb: CallbackQuery):
    c = CACHE.get(cb.from_user.id)
    if not c:
        return
    c["i"] += 1 if cb.data == "next" else -1
    c["i"] = max(0, min(c["i"], len(c["data"]) - 1))
    item = c["data"][c["i"]]
    text = f"**{item.get('title')}**\n💰 {item.get('price')}\n🔗 {item.get('link')}"
    await cb.message.edit_text(text, reply_markup=product_kb(c["i"], len(c["data"]), item.get("link")), parse_mode="Markdown")
    await cb.answer()

# ---------- PREMIUM ----------
@dp.callback_query(F.data == "premium")
async def premium(cb: CallbackQuery):
    code = ref_code(cb.from_user.id)
    text = f"""💰 Premium (Reklamsız)

Ücret: 45 TL
IBAN:
`{IBAN}`
Referans Kodun:
`{code}`"""
    await cb.message.edit_text(text, parse_mode="Markdown")
    await cb.answer()

# ---------- MAIN ----------
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())