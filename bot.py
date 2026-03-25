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

# ====================== AYARLAR (.env DOSYASINDAN OKUNUYOR) ======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
IBAN = os.getenv("IBAN")

PREMIUM_PRICE = 45      # Reklam kaldırma ücreti (TL)
AD_PRICE = 85           # Reklam verme ücreti (TL)
BOT_NAME = "FiyatAvcısıBot"   # Bot ismi
MY_TELEGRAM = "@Vortex2000"

if not all([BOT_TOKEN, SERPAPI_KEY, ADMIN_ID, IBAN]):
    raise ValueError("❌ .env dosyasında BOT_TOKEN, SERPAPI_KEY, ADMIN_ID veya IBAN eksik!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DB_NAME = "shopping_bot.db"

# Son arama sonuçlarını hafızada tut (favori ekleme için)
RESULTS_CACHE: dict[int, list] = {}

# ====================== VERİTABANI ======================
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
        await db.commit()

async def save_user(user_id: int, username: str = None, first_name: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT OR REPLACE INTO users (user_id, username, first_name, joined_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, username, first_name, datetime.now().isoformat()))
        await db.commit()

async def is_premium(user_id: int) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT 1 FROM premium_users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None

async def set_premium(user_id: int, ref_code: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO premium_users VALUES (?, ?, ?)",
                         (user_id, datetime.now().isoformat(), ref_code))
        await db.commit()

# ====================== STATES ======================
class SearchStates(StatesGroup):
    waiting_query = State()
    waiting_min_price = State()
    waiting_max_price = State()

class AdminStates(StatesGroup):
    waiting_ref_code = State()
    waiting_ad_text = State()

# ====================== YARDIMCI FONKSİYONLAR ======================
def generate_ref_code(prefix: str, user_id: int) -> str:
    random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"{prefix}-{user_id}-{random_part}"

def get_query_hash(query: str, min_p=None, max_p=None, sort="relevance"):
    key = f"{query.lower()}_{min_p}_{max_p}_{sort}"
    return hashlib.md5(key.encode()).hexdigest()

async def get_cached_results(query_hash: str):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT results_json FROM searches WHERE query_hash = ? AND created_at > ?",
            (query_hash, (datetime.now() - timedelta(days=1)).isoformat())
        ) as cursor:
            row = await cursor.fetchone()
            return json.loads(row[0]) if row else None

async def cache_results(query_hash: str, results: dict):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO searches VALUES (?, ?, ?)",
                         (query_hash, json.dumps(results), datetime.now().isoformat()))
        await db.commit()

async def search_products(query: str, min_price=None, max_price=None, sort_type="relevance"):
    tbs_map = {
        "relevance": None,
        "ucuz": "p_ord:p",
        "pahali": "p_ord:pd",
        "puan": "p_ord:rv"
    }
    params = {
        "api_key": SERPAPI_KEY,
        "engine": "google_shopping",
        "q": query,
        "gl": "tr",
        "hl": "tr",
        "num": 3
    }
    if min_price:
        params["min_price"] = min_price
    if max_price:
        params["max_price"] = max_price
    if tbs_map.get(sort_type):
        params["tbs"] = tbs_map[sort_type]

    q_hash = get_query_hash(query, min_price, max_price, sort_type)
    cached = await get_cached_results(q_hash)
    if cached:
        return cached

    search = GoogleSearch(params)
    results = search.get_dict()
    await cache_results(q_hash, results)
    return results

def product_keyboard(index: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Favoriye Ekle", callback_data=f"add_fav:{index}")],
        [InlineKeyboardButton(text="🔍 Daha Fazla Bilgi", callback_data=f"detail:{index}")],
        [InlineKeyboardButton(text="🔙 Ana Menü", callback_data="back_to_menu")]
    ])

async def broadcast_ad(text: str):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            rows = await cursor.fetchall()
            for (user_id,) in rows:
                if await is_premium(user_id):
                    continue
                try:
                    await bot.send_message(
                        user_id,
                        f"🤑 **REKLAM** 🤑\n\n{text}\n\nReklamları kaldırmak için {MY_TELEGRAM} ile iletişime geç.",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

# ====================== ANA MENÜ ======================
@dp.message(Command("start"))
async def start(message: Message):
    await save_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    is_prem = await is_premium(message.from_user.id)

    welcome_text = (
        f"👋 Hoş geldin! Ben **{BOT_NAME}**\n\n"
        "Hızlıca ürün ara, en ucuz fiyatları bul, favorilerine ekle!\n"
        "Türkiye'deki satıcıları öncelikli gösteriyorum."
    )

    kb = [
        [InlineKeyboardButton(text="🔍 Ürün Ara", callback_data="search")],
        [InlineKeyboardButton(text="⭐ Favorilerim", callback_data="my_favorites")]
    ]
    if not is_prem:
        kb.append([InlineKeyboardButton(text="💰 Reklamları Kaldır", callback_data="remove_ads")])
    else:
        kb.append([InlineKeyboardButton(text="✅ Premium Aktif", callback_data="already_premium")])

    if message.from_user.id == ADMIN_ID:
        kb.extend([
            [InlineKeyboardButton(text="Reklam Ver 🤑", callback_data="give_ad")],
            [InlineKeyboardButton(text="Ödemeleri Onayla", callback_data="approve_payment")]
        ])

    await message.answer(welcome_text, parse_mode="Markdown",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

# ====================== ARAMA SİSTEMİ ======================
@dp.callback_query(F.data == "search")
async def start_search(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Aramak istediğin ürünü yaz (örnek: airpods pro, iphone 15):")
    await state.set_state(SearchStates.waiting_query)
    await callback.answer()

@dp.message(SearchStates.waiting_query)
async def process_query(message: Message, state: FSMContext):
    query = message.text.strip()
    await state.update_data(query=query)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Filtreleri Atla → Hemen Ara", callback_data="show_results")],
        [InlineKeyboardButton(text="Minimum Fiyat Belirle", callback_data="set_min")],
        [InlineKeyboardButton(text="Maksimum Fiyat Belirle", callback_data="set_max")],
        [InlineKeyboardButton(text="Sıralama Seç", callback_data="set_sort")]
    ])
    await message.answer(f"“{query}” için arama yapılacak.\nFiltre eklemek ister misin?", reply_markup=kb)

@dp.callback_query(F.data.in_({"set_min", "set_max", "set_sort", "show_results"}))
async def handle_filters(callback: CallbackQuery, state: FSMContext):
    if callback.data == "set_min":
        await callback.message.edit_text("Minimum fiyat girin (TL):")
        await state.set_state(SearchStates.waiting_min_price)
    elif callback.data == "set_max":
        await callback.message.edit_text("Maksimum fiyat girin (TL):")
        await state.set_state(SearchStates.waiting_max_price)
    elif callback.data == "set_sort":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="En Ucuz", callback_data="sort_ucuz")],
            [InlineKeyboardButton(text="En Pahalı", callback_data="sort_pahali")],
            [InlineKeyboardButton(text="En Çok Puanlı", callback_data="sort_puan")],
            [InlineKeyboardButton(text="Varsayılan", callback_data="sort_relevance")]
        ])
        await callback.message.edit_text("Sıralama nasıl olsun?", reply_markup=kb)
    else:
        await show_search_results(callback.message, state)
    await callback.answer()

@dp.message(SearchStates.waiting_min_price)
async def set_min_price(message: Message, state: FSMContext):
    await state.update_data(min_price=message.text.strip())
    await message.answer("Minimum fiyat kaydedildi.")
    await show_search_results(message, state)

@dp.message(SearchStates.waiting_max_price)
async def set_max_price(message: Message, state: FSMContext):
    await state.update_data(max_price=message.text.strip())
    await message.answer("Maksimum fiyat kaydedildi.")
    await show_search_results(message, state)

@dp.callback_query(F.data.startswith("sort_"))
async def set_sort(callback: CallbackQuery, state: FSMContext):
    sort_type = callback.data.replace("sort_", "")
    await state.update_data(sort_type=sort_type)
    await callback.message.edit_text(f"Sıralama: {sort_type.upper()}")
    await show_search_results(callback.message, state)

async def show_search_results(msg, state: FSMContext):
    data = await state.get_data()
    query = data.get("query")
    min_p = data.get("min_price")
    max_p = data.get("max_price")
    sort_t = data.get("sort_type", "relevance")

    results = await search_products(query, min_p, max_p, sort_t)
    shopping = results.get("shopping_results", [])[:3]

    if not shopping:
        await msg.answer("Sonuç bulunamadı 😔")
        await state.clear()
        return

    user_id = msg.from_user.id if hasattr(msg, "from_user") else msg.chat.id
    RESULTS_CACHE[user_id] = shopping

    for i, product in enumerate(shopping):
        title = product.get("title", "İsim yok")
        price = product.get("price", "Fiyat yok")
        source = product.get("source", "Satıcı yok")
        thumbnail = product.get("thumbnail")
        caption = f"**{title}**\n💰 {price}\n🏪 {source}"

        kb = product_keyboard(i)

        if thumbnail:
            await bot.send_photo(user_id, thumbnail, caption=caption, parse_mode="Markdown", reply_markup=kb)
        else:
            await bot.send_message(user_id, caption, parse_mode="Markdown", reply_markup=kb)

    await state.clear()

# ====================== ÜRÜN İŞLEMLERİ ======================
@dp.callback_query(F.data.startswith("add_fav:"))
async def add_to_favorite(callback: CallbackQuery):
    user_id = callback.from_user.id
    index = int(callback.data.split(":")[1])
    product = RESULTS_CACHE.get(user_id, [None])[index]

    if not product:
        await callback.answer("Hata: Sonuç bulunamadı.")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT OR IGNORE INTO favorites 
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            product.get("title"),
            product.get("extracted_price"),
            product.get("link"),
            product.get("thumbnail"),
            product.get("source"),
            datetime.now().isoformat()
        ))
        await db.commit()

    await callback.answer("⭐ Favorilere eklendi!")

@dp.callback_query(F.data.startswith("detail:"))
async def show_detail(callback: CallbackQuery):
    user_id = callback.from_user.id
    index = int(callback.data.split(":")[1])
    product = RESULTS_CACHE.get(user_id, [None])[index]

    if not product:
        await callback.answer("Hata!")
        return

    detail_text = (
        f"**{product.get('title')}**\n\n"
        f"💰 Fiyat: {product.get('price')}\n"
        f"🏪 Satıcı: {product.get('source')}\n"
        f"⭐ Puan: {product.get('rating', 'Yok')}\n"
        f"📝 Açıklama: {product.get('snippet', 'Yok')}\n\n"
        f"🔗 Link: {product.get('link')}"
    )
    await callback.message.answer(detail_text, parse_mode="Markdown", disable_web_page_preview=True)
    await callback.answer()

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    await start(callback.message)
    await callback.answer()

# ====================== FAVORİLER ======================
@dp.callback_query(F.data == "my_favorites")
async def show_favorites(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT title, price, link FROM favorites WHERE user_id = ?", (user_id,)
        ) as cursor:
            favs = await cursor.fetchall()

    if not favs:
        await callback.message.edit_text("Henüz favorin yok ⭐")
        return

    text = "⭐ **Favorilerim**\n\n"
    for title, price, _ in favs:
        text += f"• {title} — {price} TL\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Ana Menü", callback_data="back_to_menu")]
    ])

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)

# ====================== REKLAM KALDIRMA ======================
@dp.callback_query(F.data == "remove_ads")
async def remove_ads(callback: CallbackQuery):
    if await is_premium(callback.from_user.id):
        await callback.answer("Zaten premium'sun!")
        return

    ref_code = generate_ref_code("PREMIUM", callback.from_user.id)
    text = (
        f"💰 **Reklamları Kaldır**\n\n"
        f"Ücret: {PREMIUM_PRICE} TL\n"
        f"IBAN: `{IBAN}`\n"
        f"Referans Kodu: `{ref_code}`\n\n"
        f"İşCep’ten havale yaparken **açıklama kısmına** tam olarak bu kodu yaz.\n"
        f"Ödeme sonrası admin onaylayınca reklamlar sonsuza kadar kalkacak."
    )
    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()

# ====================== REKLAM VERME ======================
@dp.callback_query(F.data == "give_ad")
async def start_give_ad(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Bu özellik sadece admin'e aittir!")
        return
    await callback.message.edit_text("Reklam metnini gönder (herkese bu şekilde yayınlanacak):")
    await state.set_state(AdminStates.waiting_ad_text)
    await callback.answer()

@dp.message(AdminStates.waiting_ad_text)
async def receive_ad_text(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await broadcast_ad(message.text)
    await message.answer("✅ Reklam tüm premium olmayan kullanıcılara gönderildi!")
    await state.clear()

# ====================== ADMIN ÖDEME ONAYI ======================
@dp.callback_query(F.data == "approve_payment")
async def approve_payment(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Sadece admin!")
        return
    await callback.message.edit_text("Bankadan gördüğün **Referans Kodunu** tam olarak yaz:")
    await state.set_state(AdminStates.waiting_ref_code)
    await callback.answer()

@dp.message(AdminStates.waiting_ref_code)
async def process_ref_code(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    ref = message.text.strip().upper()

    try:
        if ref.startswith("PREMIUM-"):
            user_id = int(ref.split("-")[1])
            await set_premium(user_id, ref)
            await message.answer(f"✅ Premium aktif edildi!\nKullanıcı ID: {user_id}")
        elif ref.startswith("AD-"):
            user_id = int(ref.split("-")[1])
            await message.answer(f"✅ Reklam verme ödemesi onaylandı!\nKullanıcı ID: {user_id}\n\nŞimdi reklam metnini gir:")
            await state.set_state(AdminStates.waiting_ad_text)
        else:
            await message.answer("❌ Geçersiz referans kodu formatı!")
    except Exception:
        await message.answer("❌ Kod okunamadı. Tam olarak kopyala-yapıştır yapın.")

    await state.clear()

# ====================== REKLAM İSTEĞİ ======================
@dp.message()
async def handle_any_message(message: Message):
    if "reklam vermek istiyorum" in message.text.lower():
        ref_code = generate_ref_code("AD", message.from_user.id)
        text = (
            f"🤑 **Reklam Vermek İstiyorsun**\n\n"
            f"Ücret: {AD_PRICE} TL\n"
            f"IBAN: `{IBAN}`\n"
            f"Referans Kodu: `{ref_code}`\n\n"
            f"Ödemeyi yaptıktan sonra admin onaylayınca reklamın yayınlanacak."
        )
        await message.answer(text, parse_mode="Markdown")

# ====================== BAŞLAT ======================
async def main():
    await init_db()
    print(f"✅ {BOT_NAME} çalışıyor... 🚀")
    print(f"Admin ID: {ADMIN_ID} | IBAN yüklendi")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
