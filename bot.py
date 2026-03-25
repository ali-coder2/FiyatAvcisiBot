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
    choose_filter = State()
    min_price = State()
    max_price = State()
    target_price = State()

# ---------- DB ----------
async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS fav (user INTEGER, link TEXT, title TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS alerts (user INTEGER, link TEXT, target REAL)")
        await db.commit()

# ---------- SEARCH ----------
async def search(q, min_p=None, max_p=None):
    params = {
        "api_key": SERPAPI_KEY,
        "engine": "google_shopping",
        "q": q,
        "hl": "tr",
        "gl": "tr",
        "num": 10
    }

    # 🔥 FIX: None değilse gönder
    if min_p is not None:
        params["min_price"] = min_p
    if max_p is not None:
        params["max_price"] = max_p

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: GoogleSearch(params).get_dict())

# ---------- UI ----------
def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Ara", callback_data="search")],
        [InlineKeyboardButton(text="⭐ Favoriler", callback_data="fav")],
        [InlineKeyboardButton(text="📊 Takipler", callback_data="alerts")]
    ])

def filter_choice_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Bütçe Belirle", callback_data="set_budget")],
        [InlineKeyboardButton(text="⚡ Filtresiz Ara", callback_data="no_filter")]
    ])

def product_kb(i, total, link):
    nav = []
    if i > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data="prev"))
    if i < total-1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data="next"))

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Ürüne Git", url=link)],
        nav,
        [InlineKeyboardButton(text="🔙 Menü", callback_data="menu")]
    ])

def back():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Menü", callback_data="menu")]
    ])

# ---------- SHOW ----------
async def show(cb, uid):
    data = CACHE.get(uid)
    if not data:
        return

    i = data["i"]
    p = data["data"][i]

    title = p.get("title")
    price = p.get("price")
    link = p.get("link")
    img = p.get("thumbnail")

    text = f"**{title}**\n💰 {price}\n\n🔗 {link}"

    try:
        await cb.message.delete()
        await cb.message.answer_photo(
            photo=img,
            caption=text,
            parse_mode="Markdown",
            reply_markup=product_kb(i, len(data["data"]), link)
        )
    except:
        pass

# ---------- START ----------
@dp.message(Command("start"))
async def start(m: Message):
    await m.answer("Hoş geldin!", reply_markup=menu())

# ---------- MENU ----------
@dp.callback_query(F.data == "menu")
async def mnu(cb: CallbackQuery):
    await cb.message.delete()
    await cb.message.answer("Menü", reply_markup=menu())
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

    await m.answer("Filtre seç:", reply_markup=filter_choice_kb())
    await state.set_state(States.choose_filter)

# ---------- FILTER SEÇİM ----------
@dp.callback_query(F.data == "no_filter")
async def no_filter(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    res = await search(data["q"])
    items = res.get("shopping_results", [])

    if not items:
        await cb.message.answer("Sonuç yok")
        return

    CACHE[cb.from_user.id] = {"data": items, "i": 0}

    msg = await cb.message.answer("Yükleniyor...")
    await show(type("obj", (), {"message": msg}), cb.from_user.id)

    await state.clear()
    await cb.answer()

@dp.callback_query(F.data == "set_budget")
async def set_budget(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer("Minimum fiyat:")
    await state.set_state(States.min_price)
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
    await m.answer("Maksimum fiyat:")
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

    res = await search(data["q"], data.get("min"), val)
    items = res.get("shopping_results", [])

    if not items:
        await m.answer("❌ Bu bütçede ürün bulunamadı.")
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

# ---------- FAVORİ ----------
@dp.callback_query(F.data == "fav")
async def fav(cb: CallbackQuery):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT title FROM fav WHERE user=?", (cb.from_user.id,)) as c:
            rows = await c.fetchall()

    txt = "Favorin yok" if not rows else "\n".join([r[0] for r in rows])
    await cb.message.edit_text(txt, reply_markup=back())
    await cb.answer()

# ---------- TAKİPLER ----------
@dp.callback_query(F.data == "alerts")
async def alerts(cb: CallbackQuery):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT target FROM alerts WHERE user=?", (cb.from_user.id,)) as c:
            rows = await c.fetchall()

    txt = "Takip yok" if not rows else "\n".join([str(r[0])+" TL" for r in rows])
    await cb.message.edit_text(txt, reply_markup=back())
    await cb.answer()

# ---------- MAIN ----------
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())