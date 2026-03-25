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

# ========== STATES ==========

class States(StatesGroup):
    query = State()
    min_price = State()
    max_price = State()
    target_price = State()
    ref = State()
    ad = State()

# ========== DB ==========

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS premium (id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS fav (user INTEGER, link TEXT, title TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS alerts (user INTEGER, link TEXT, target REAL)")
        await db.commit()

# ========== HELPERS ==========

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
        params["min_price"] = str(int(min_p))
    if max_p is not None:
        params["max_price"] = str(int(max_p))

    print(f"API Çağrısı: q={q}, min={min_p}, max={max_p}")
    
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, lambda: GoogleSearch(params).get_dict())
        print(f"API Yanıtı: {list(result.keys())}")
        return result
    except Exception as e:
        print(f"API Hatası: {e}")
        return {"shopping_results": []}

# ========== UI ==========

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
    keyboard = []
    
    # Ürüne git butonu
    keyboard.append([InlineKeyboardButton(text="🔗 Ürüne Git", url=link)])
    
    # Favori ve Takip butonları
    keyboard.append([
        InlineKeyboardButton(text="⭐ Favori", callback_data=f"fav_add:{i}"),
        InlineKeyboardButton(text="🔔 Takip", callback_data=f"track:{i}")
    ])
    
    # Navigasyon butonları
    nav_row = []
    if i > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Önceki", callback_data="prev"))
    if i < total - 1:
        nav_row.append(InlineKeyboardButton(text="Sonraki ➡️", callback_data="next"))
    
    if nav_row:  # Sadece navigasyon butonu varsa ekle
        keyboard.append(nav_row)
    
    # Menü butonu
    keyboard.append([InlineKeyboardButton(text="🔙 Menü", callback_data="menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Menü", callback_data="menu")]
    ])

def budget_choice_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Bütçe Belirle", callback_data="budget")],
        [InlineKeyboardButton(text="🚀 Filtresiz", callback_data="nofilter")]
    ])

# ========== SHOW ==========

async def show_message(message, uid, is_callback=False):
    data = CACHE.get(uid)
    if not data:
        await message.answer("Veri bulunamadı.")
        return

    i = data["i"]
    if i >= len(data["data"]):
        i = 0
        data["i"] = 0
    
    p = data["data"][i]

    title = p.get("title", "Başlık yok")
    price = p.get("price", "Fiyat yok")
    link = p.get("link", "")
    img = p.get("thumbnail")

    text = f"**{title}**\n💰 {price}\n\n🔗 {link}"
    
    markup = product_kb(i, len(data["data"]), link)

    try:
        if img:
            # Önceki mesajı sil
            if is_callback:
                try:
                    await message.delete()
                except:
                    pass
            await message.answer_photo(
                photo=img,
                caption=text,
                parse_mode="Markdown",
                reply_markup=markup
            )
        else:
            if is_callback:
                await message.edit_text(text, parse_mode="Markdown", reply_markup=markup)
            else:
                await message.answer(text, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        print(f"Show hatası: {e}")
        try:
            await message.answer(text, parse_mode="Markdown", reply_markup=markup)
        except Exception as e2:
            print(f"Show hatası 2: {e2}")

# ========== START ==========

@dp.message(Command("start"))
async def start(m: Message, state: FSMContext):
    await state.clear()
    
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
        await db.commit()

    prem = await is_premium(m.from_user.id)
    await m.answer("👋 Hoş geldin! Aşağıdaki menüden işlem seçebilirsin.", reply_markup=menu_kb(prem, m.from_user.id == ADMIN_ID))

# ========== MENU ==========

@dp.callback_query(F.data == "menu")
async def menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    prem = await is_premium(cb.from_user.id)
    
    try:
        await cb.message.delete()
    except:
        pass
        
    await cb.message.answer("📋 Ana Menü", reply_markup=menu_kb(prem, cb.from_user.id == ADMIN_ID))
    await cb.answer()

# ========== SEARCH FLOW ==========

@dp.callback_query(F.data == "search")
async def s(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("🔍 Hangi ürünü aramak istiyorsun?")
    await state.set_state(States.query)
    await cb.answer()

@dp.message(States.query)
async def q(m: Message, state: FSMContext):
    await state.update_data(q=m.text)
    await m.answer("Filtre seçimi yap:", reply_markup=budget_choice_kb())

@dp.callback_query(F.data.in_(["budget", "nofilter"]))
async def search_type(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    query = data.get("q")
    
    if not query:
        await cb.message.edit_text("❌ Önce ürün adı yazmalısınız. /start ile yeniden başlayın.")
        await state.clear()
        await cb.answer()
        return

    if cb.data == "budget":
        await cb.message.edit_text("💰 Minimum fiyat (TL) gir:")
        await state.set_state(States.min_price)
    else:  # nofilter
        await cb.message.edit_text("🔍 Aranıyor...")
        
        res = await search(query)
        items = res.get("shopping_results", [])
        
        print(f"Filtresiz arama sonuç: {len(items)} ürün")
        
        if not items:
            await cb.message.edit_text("❌ Aradığınız ürün bulunamadı.", reply_markup=back_kb())
            await state.clear()
            await cb.answer()
            return
        
        CACHE[cb.from_user.id] = {"data": items, "i": 0}
        await show_message(cb.message, cb.from_user.id, is_callback=True)
        await state.clear()
    
    await cb.answer()

@dp.message(States.min_price)
async def min_p(m: Message, state: FSMContext):
    try:
        val = float(m.text)
    except:
        await m.answer("❌ Lütfen geçerli bir sayı girin.")
        return
    await state.update_data(min=val)
    await m.answer("💰 Maksimum fiyat (TL):")
    await state.set_state(States.max_price)

@dp.message(States.max_price)
async def max_p(m: Message, state: FSMContext):
    try:
        val = float(m.text)
    except:
        await m.answer("❌ Lütfen geçerli bir sayı girin.")
        return

    data = await state.get_data()
    min_val = data.get("min")
    query = data.get("q")
    
    if not query:
        await m.answer("❌ Bir hata oluştu. Lütfen /start ile yeniden başlayın.")
        await state.clear()
        return
    
    loading_msg = await m.answer("🔍 Aranıyor...")
    
    res = await search(query, min_val, val)
    items = res.get("shopping_results", [])
    
    print(f"Filtreli arama sonuç: {len(items)} ürün (min: {min_val}, max: {val})")
    
    if not items:
        await loading_msg.edit_text("❌ Aradığınız ürün bulunamadı.", reply_markup=back_kb())
        await state.clear()
        return

    CACHE[m.from_user.id] = {"data": items, "i": 0}
    
    try:
        await loading_msg.delete()
    except:
        pass
    
    await show_message(m, m.from_user.id, is_callback=False)
    await state.clear()

# ========== NAV ==========

@dp.callback_query(F.data.in_(["next", "prev"]))
async def nav(cb: CallbackQuery):
    c = CACHE.get(cb.from_user.id)
    if not c:
        await cb.answer("Veri bulunamadı")
        return

    if cb.data == "next":
        c["i"] += 1
    else:
        c["i"] -= 1
    
    # Sınır kontrolü
    if c["i"] < 0:
        c["i"] = 0
    if c["i"] >= len(c["data"]):
        c["i"] = len(c["data"]) - 1
    
    await show_message(cb.message, cb.from_user.id, is_callback=True)
    await cb.answer()

# ========== FAVORİ ==========

@dp.callback_query(F.data.startswith("fav_add:"))
async def fav_add(cb: CallbackQuery):
    i = int(cb.data.split(":")[1])
    p = CACHE[cb.from_user.id]["data"][i]

    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT INTO fav VALUES (?, ?, ?)",
                         (cb.from_user.id, p.get("link"), p.get("title")))
        await db.commit()

    await cb.answer("✅ Favorilere eklendi")

@dp.callback_query(F.data == "fav")
async def fav(cb: CallbackQuery):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT title FROM fav WHERE user=?", (cb.from_user.id,)) as c:
            rows = await c.fetchall()

    txt = "⭐ Favorin yok" if not rows else "⭐ Favoriler:\n\n" + "\n".join([f"• {r[0]}" for r in rows])
    await cb.message.edit_text(txt, reply_markup=back_kb())
    await cb.answer()

# ========== TAKİPLER ==========

@dp.callback_query(F.data == "alerts")
async def alerts(cb: CallbackQuery):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT link, target FROM alerts WHERE user=?", (cb.from_user.id,)) as c:
            rows = await c.fetchall()

    txt = "📊 Takip yok" if not rows else "📊 Takipler:\n\n" + "\n".join([f"• Hedef: {r[1]} TL" for r in rows])
    await cb.message.edit_text(txt, reply_markup=back_kb())
    await cb.answer()

# ========== TAKİP EKLE ==========

@dp.callback_query(F.data.startswith("track:"))
async def track(cb: CallbackQuery, state: FSMContext):
    i = int(cb.data.split(":")[1])
    p = CACHE[cb.from_user.id]["data"][i]

    await state.update_data(p=p)
    await cb.message.answer("🎯 Hedef fiyat gir (TL):")
    await state.set_state(States.target_price)
    await cb.answer()

@dp.message(States.target_price)
async def set_price(m: Message, state: FSMContext):
    try:
        price = float(m.text)
    except:
        await m.answer("❌ Lütfen geçerli bir sayı girin.")
        return

    data = await state.get_data()
    p = data.get("p")

    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT INTO alerts VALUES (?, ?, ?)",
                         (m.from_user.id, p.get("link"), price))
        await db.commit()

    await m.answer("✅ Takip başlatıldı")
    await state.clear()

# ========== PREMIUM ==========

@dp.callback_query(F.data == "premium")
async def prem(cb: CallbackQuery):
    code = ref_code(cb.from_user.id)

    text = f"""💰 Premium (Reklamsız)

Ücret: 45 TL

IBAN:
`{IBAN}`

Referans Kodun:
`{code}`

1️⃣ IBAN'a ödeme yap
2️⃣ Açıklamaya kodu yaz
3️⃣ Onay sonrası premium aktif
"""
    await cb.message.edit_text(text, parse_mode="Markdown")
    await cb.answer()

# ========== MAIN ==========

async def main():
    await init_db()
    print("🤖 Bot başlatılıyor...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
