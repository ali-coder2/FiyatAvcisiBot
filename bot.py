import asyncio
import random
import string
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

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DB = "db.sqlite"
CACHE = {}

# ---------- STATES ----------
class States(StatesGroup):
    query = State()
    min_price = State()
    max_price = State()
    target_price = State()
    ref = State()
    ad = State()

# ---------- DB ----------
async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS premium (id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS fav (user INTEGER, link TEXT, title TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS alerts (user INTEGER, link TEXT, target REAL)")
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

# ---------- UI ----------
def menu_kb(prem, admin):
    kb = [
        [InlineKeyboardButton(text="🔍 Ara", callback_data="search")],
        [InlineKeyboardButton(text="⭐ Favoriler", callback_data="fav")],
        [InlineKeyboardButton(text="📊 Takipler", callback_data="alerts")]
    ]
    if not prem:
        kb.append([InlineKeyboardButton(text="💰 Reklam Kaldır", callback_data="premium")])
    else:
        kb.append([InlineKeyboardButton(text="✅ Premium", callback_data="noop")])
    if admin:
        kb.append([InlineKeyboardButton(text="📢 Reklam", callback_data="ad")])
        kb.append([InlineKeyboardButton(text="💳 Onay", callback_data="approve")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def product_kb(i, total, link):
    nav = []
    if i > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data="prev"))
    if i < total-1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data="next"))

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Ürüne Git", url=link)],
        [InlineKeyboardButton(text="⭐ Favori", callback_data=f"fav_add:{i}")],
        [InlineKeyboardButton(text="🔔 Takip", callback_data=f"track:{i}")],
        nav,
        [InlineKeyboardButton(text="🔙 Menü", callback_data="menu")]
    ])

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Menü", callback_data="menu")]
    ])

def budget_choice_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Bütçe Belirle", callback_data="budget")],
        [InlineKeyboardButton(text="Filtresiz", callback_data="nofilter")]
    ])

# ---------- SHOW ----------
async def show(cb, uid):
    data = CACHE.get(uid)
    if not data:
        return

    i = data["i"]
    i = max(0, min(i, len(data["data"]) - 1))
    data["i"] = i

    p = data["data"][i]

    title = p.get("title")
    price = p.get("price")
    link = p.get("link")
    img = p.get("thumbnail")

    text = f"**{title}**\n💰 {price}\n\n🔗 {link}"

    try:
        if img:
            await cb.message.answer_photo(
                photo=img,
                caption=text,
                parse_mode="Markdown",
                reply_markup=product_kb(i, len(data["data"]), link)
            )
        else:
            await cb.message.edit_text(
                text,
                parse_mode="Markdown",
                reply_markup=product_kb(i, len(data["data"]), link)
            )
    except:
        pass

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
async def s(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Ürün adı yaz:")
    await state.set_state(States.query)
    await cb.answer()

@dp.message(States.query)
async def q(m: Message, state: FSMContext):
    await state.update_data(q=m.text)

    # 🔥 backup fix
    CACHE[m.from_user.id] = {"query": m.text}

    await m.answer("Seçim yap:", reply_markup=budget_choice_kb())

@dp.callback_query(F.data.in_(["budget", "nofilter"]))
async def search_type(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    query = data.get("q")

    # 🔥 fallback fix
    if not query:
        query = CACHE.get(cb.from_user.id, {}).get("query")

    if not query:
        await cb.message.edit_text("Önce ürün adı yazmalısınız.")
        await state.set_state(States.query)
        return

    if cb.data == "budget":
        await cb.message.edit_text("Minimum fiyat (TL) gir:")
        await state.set_state(States.min_price)

    else:
        res = await search(query)
        items = res.get("shopping_results", [])

        if not items:
            await cb.message.edit_text("Ürün bulunamadı.", reply_markup=back_kb())
            return

        CACHE[cb.from_user.id] = {"data": items, "i": 0}
        await show(cb, cb.from_user.id)
        await state.clear()

    await cb.answer()

# ---------- MIN ----------
@dp.message(States.min_price)
async def min_p(m: Message, state: FSMContext):
    try:
        val = float(m.text)
    except:
        await m.answer("Sayı gir")
        return

    await state.update_data(min=val)
    await m.answer("Maksimum fiyat (TL):")
    await state.set_state(States.max_price)

# ---------- MAX ----------
@dp.message(States.max_price)
async def max_p(m: Message, state: FSMContext):
    try:
        val = float(m.text)
    except:
        await m.answer("Sayı gir")
        return

    data = await state.get_data()

    query = data.get("q") or CACHE.get(m.from_user.id, {}).get("query")

    res = await search(query, data.get("min"), val)
    items = res.get("shopping_results", [])

    if not items:
        await m.answer("Sonuç yok")
        return

    CACHE[m.from_user.id] = {"data": items, "i": 0}
    msg = await m.answer("Yükleniyor...")
    await show(type("obj", (), {"message": msg}), m.from_user.id)

    await state.clear()

# ---------- NAV ----------
@dp.callback_query(F.data.in_(["next", "prev"]))
async def nav(cb: CallbackQuery):
    c = CACHE.get(cb.from_user.id)
    if not c:
        return

    c["i"] += 1 if cb.data == "next" else -1
    await show(cb, cb.from_user.id)
    await cb.answer()

# ---------- MAIN ----------
async def main():
    await init_db()

    # 🔥 conflict fix
    await bot.delete_webhook(drop_pending_updates=True)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())