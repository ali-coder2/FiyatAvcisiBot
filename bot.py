import asyncio
import random
import string
import re
from datetime import datetime

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

# ====================== AYARLAR ======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
IBAN = os.getenv("IBAN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DB = "db.sqlite"
CACHE = {}  # user_id: {"data": [...], "i": 0}

# ====================== STATES ======================
class States(StatesGroup):
    query = State()
    min_price = State()
    max_price = State()
    target_price = State()
    ad_text = State()
    approve_code = State()

# ====================== DB ======================
async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS premium (id INTEGER PRIMARY KEY)")
        await db.execute("""CREATE TABLE IF NOT EXISTS fav (
            user INTEGER, 
            link TEXT, 
            title TEXT,
            price TEXT,
            UNIQUE(user, link)
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS alerts (
            user INTEGER, 
            link TEXT, 
            title TEXT,
            current_price TEXT,
            target_price REAL,
            last_checked TEXT,
            UNIQUE(user, link)
        )""")
        await db.commit()

# ====================== HELPERS ======================
def ref_code(uid):
    return f"PREM-{uid}-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

async def is_premium(uid):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT 1 FROM premium WHERE id=?", (uid,)) as c:
            return await c.fetchone() is not None

def extract_price(price_str):
    if not price_str:
        return None
    numbers = re.findall(r'[\d.,]+', str(price_str))
    if numbers:
        num = numbers[0].replace('.', '').replace(',', '.')
        try:
            return float(num)
        except:
            return None
    return None

def safe_edit_or_send(message, text, reply_markup=None, parse_mode="Markdown"):
    """Mesajı güvenli şekilde edit et veya yeni gönder"""
    try:
        return message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except:
        try:
            return message.delete()
        except:
            pass
        return message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)

# ====================== FİYAT TAKİP SCHEDULER ======================
async def check_price_drops():
    while True:
        try:
            async with aiosqlite.connect(DB) as db:
                async with db.execute(
                    "SELECT user, link, title, current_price, target_price FROM alerts"
                ) as cursor:
                    alerts = await cursor.fetchall()

            for alert in alerts:
                user_id, link, title, old_price_str, target_price = alert

                res = await search(title)
                items = res.get("shopping_results", [])

                for item in items:
                    if item.get("link") == link:
                        current_price_str = item.get("price", "Fiyat yok")
                        current_price_val = extract_price(current_price_str)

                        async with aiosqlite.connect(DB) as db:
                            await db.execute(
                                "UPDATE alerts SET current_price = ?, last_checked = ? WHERE user = ? AND link = ?",
                                (current_price_str, datetime.now().isoformat(), user_id, link)
                            )
                            await db.commit()

                        if current_price_val and current_price_val <= target_price:
                            try:
                                await bot.send_message(
                                    user_id,
                                    f"🎉 **Fiyat Düştü!**\n\n"
                                    f"📦 {title}\n"
                                    f"💰 Eski: {old_price_str}\n"
                                    f"💰 Yeni: {current_price_str}\n"
                                    f"🎯 Hedef: {target_price} TL\n\n"
                                    f"🔗 [Ürüne Git]({link})",
                                    parse_mode="Markdown",
                                    disable_web_page_preview=True
                                )
                                async with aiosqlite.connect(DB) as db:
                                    await db.execute("DELETE FROM alerts WHERE user = ? AND link = ?", (user_id, link))
                                    await db.commit()
                            except Exception as e:
                                print(f"Bildirim hatası ({user_id}): {e}")
                        break

            await asyncio.sleep(1800)  # 30 dakika

        except Exception as e:
            print(f"Scheduler hatası: {e}")
            await asyncio.sleep(300)

# ====================== SEARCH ======================
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

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: GoogleSearch(params).get_dict())
        
        shopping = result.get("shopping_results") or result.get("inline_shopping_results") or []
        
        normalized = []
        for item in shopping:
            normalized.append({
                "title": item.get("title") or item.get("name", "Başlık yok"),
                "price": item.get("price") or item.get("extracted_price", "Fiyat yok"),
                "link": item.get("link") or item.get("product_link", "#"),
                "thumbnail": item.get("thumbnail") or item.get("image"),
                "source": item.get("source") or item.get("merchant", "Bilinmeyen")
            })
        return {"shopping_results": normalized}
    except Exception as e:
        print(f"SerpApi Hatası: {e}")
        return {"shopping_results": []}

# ====================== MENÜ ======================
def menu_kb(prem: bool, is_admin: bool):
    kb = [
        [InlineKeyboardButton(text="🔍 Ara", callback_data="search")],
        [InlineKeyboardButton(text="⭐ Favoriler", callback_data="fav")],
        [InlineKeyboardButton(text="👀 Fiyat Takip", callback_data="alerts")]
    ]
    if not prem:
        kb.append([InlineKeyboardButton(text="💰 Reklamları Kaldır", callback_data="premium")])
    else:
        kb.append([InlineKeyboardButton(text="✅ Premium Aktif", callback_data="noop")])

    if is_admin:
        kb.extend([
            [InlineKeyboardButton(text="📢 Reklam Gönder", callback_data="ad")],
            [InlineKeyboardButton(text="💳 Premium Onayla", callback_data="approve")]
        ])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Ana Menü", callback_data="menu")]
    ])

def product_kb(i, total, link):
    kb = [
        [InlineKeyboardButton(text="🔗 Ürüne Git", url=link)],
        [
            InlineKeyboardButton(text="⭐ Favori", callback_data=f"fav_add:{i}"),
            InlineKeyboardButton(text="🔔 Takip Et", callback_data=f"track:{i}")
        ]
    ]
    nav = []
    if i > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Önceki", callback_data="prev"))
    if i < total - 1:
        nav.append(InlineKeyboardButton(text="➡️ Sonraki", callback_data="next"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton(text="🔙 Ana Menü", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ====================== ÜRÜN GÖSTER ======================
async def show_product(msg, uid, is_callback=False):
    data = CACHE.get(uid)
    if not data or not data.get("data"):
        text = "❌ Ürün verisi bulunamadı."
        if is_callback:
            await safe_edit_or_send(msg, text, back_kb())
        else:
            await msg.answer(text, reply_markup=back_kb())
        return

    i = data["i"]
    if i >= len(data["data"]):
        i = 0
        data["i"] = 0
    if i < 0:
        i = 0
        data["i"] = 0

    p = data["data"][i]
    title = p.get("title", "Başlık yok")
    price = p.get("price", "Fiyat yok")
    link = p.get("link", "#")
    img = p.get("thumbnail")
    source = p.get("source", "Bilinmeyen")

    text = f"📦 **{title}**\n\n💰 {price}\n🏪 {source}\n\n🔗 [Ürüne Git]({link})"

    markup = product_kb(i, len(data["data"]), link)

    if img:
        if is_callback:
            try:
                await msg.delete()
            except:
                pass
        await msg.answer_photo(photo=img, caption=text, parse_mode="Markdown", reply_markup=markup)
    else:
        if is_callback:
            await safe_edit_or_send(msg, text, markup)
        else:
            await msg.answer(text, parse_mode="Markdown", reply_markup=markup)

# ====================== START ======================
@dp.message(Command("start"))
async def start(m: Message):
    await init_db()
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
        await db.commit()

    prem = await is_premium(m.from_user.id)
    await m.answer(
        "🤖 **FiyatAvcısıBot**'a hoş geldin!\n\n"
        "En ucuz fiyatları bul, takip et, favorilerine kaydet.",
        parse_mode="Markdown",
        reply_markup=menu_kb(prem, m.from_user.id == ADMIN_ID)
    )

# ====================== ANA MENÜ ======================
@dp.callback_query(F.data == "menu")
async def menu_callback(cb: CallbackQuery):
    prem = await is_premium(cb.from_user.id)
    await safe_edit_or_send(
        cb.message,
        "📋 Ana Menü - İşlem seçin:",
        menu_kb(prem, cb.from_user.id == ADMIN_ID)
    )
    await cb.answer()

# ====================== ARA ======================
@dp.callback_query(F.data == "search")
async def search_start(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit_or_send(cb.message, "🔍 Hangi ürünü aramak istiyorsun?\nÜrün adını yazın:")
    await state.set_state(States.query)
    await cb.answer()

@dp.message(States.query)
async def search_query(m: Message, state: FSMContext):
    await state.update_data(q=m.text)
    await m.answer("Filtre seçimi yap:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Bütçe Belirle", callback_data="budget")],
        [InlineKeyboardButton(text="🚀 Filtresiz Ara", callback_data="nofilter")]
    ]))

@dp.callback_query(F.data.in_(["budget", "nofilter"]))
async def search_type(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    query = data.get("q")
    if not query:
        await safe_edit_or_send(cb.message, "❌ Önce ürün adı yazmalısınız.", back_kb())
        await state.clear()
        await cb.answer()
        return

    if cb.data == "budget":
        await safe_edit_or_send(cb.message, "💰 Minimum fiyat (TL) girin:")
        await state.set_state(States.min_price)
    else:
        await safe_edit_or_send(cb.message, "🔍 Aranıyor... Lütfen bekleyin.")
        res = await search(query)
        items = res.get("shopping_results", [])

        if not items:
            await safe_edit_or_send(cb.message, "❌ Sonuç bulunamadı.", back_kb())
            await state.clear()
            await cb.answer()
            return

        CACHE[cb.from_user.id] = {"data": items, "i": 0}
        await show_product(cb.message, cb.from_user.id, is_callback=True)
        await state.clear()
    await cb.answer()

@dp.message(States.min_price)
async def min_price_handler(m: Message, state: FSMContext):
    try:
        val = float(m.text)
    except:
        await m.answer("❌ Geçerli bir sayı girin.")
        return
    await state.update_data(min=val)
    await m.answer("💰 Maksimum fiyat (TL) girin:")
    await state.set_state(States.max_price)

@dp.message(States.max_price)
async def max_price_handler(m: Message, state: FSMContext):
    try:
        val = float(m.text)
    except:
        await m.answer("❌ Geçerli bir sayı girin.")
        return

    data = await state.get_data()
    query = data.get("q")
    min_val = data.get("min")

    loading = await m.answer("🔍 Aranıyor... Lütfen bekleyin.")
    res = await search(query, min_val, val)
    items = res.get("shopping_results", [])

    if not items:
        await loading.edit_text("❌ Sonuç bulunamadı.", reply_markup=back_kb())
        await state.clear()
        return

    CACHE[m.from_user.id] = {"data": items, "i": 0}
    await show_product(loading, m.from_user.id, is_callback=False)
    await state.clear()

# ====================== NAVİGASYON ======================
@dp.callback_query(F.data.in_(["next", "prev"]))
async def nav(cb: CallbackQuery):
    c = CACHE.get(cb.from_user.id)
    if not c or not c.get("data"):
        await cb.answer("Veri bulunamadı")
        return

    if cb.data == "next":
        c["i"] += 1
    else:
        c["i"] -= 1

    if c["i"] < 0:
        c["i"] = 0
    if c["i"] >= len(c["data"]):
        c["i"] = len(c["data"]) - 1

    await show_product(cb.message, cb.from_user.id, is_callback=True)
    await cb.answer()

# ====================== FAVORİ ======================
@dp.callback_query(F.data.startswith("fav_add:"))
async def fav_add(cb: CallbackQuery):
    i = int(cb.data.split(":")[1])
    p = CACHE[cb.from_user.id]["data"][i]
    async with aiosqlite.connect(DB) as db:
        try:
            await db.execute(
                "INSERT INTO fav (user, link, title, price) VALUES (?, ?, ?, ?)",
                (cb.from_user.id, p.get("link"), p.get("title"), p.get("price"))
            )
            await db.commit()
            await cb.answer("✅ Favorilere eklendi!")
        except:
            await cb.answer("❌ Zaten favorilerde")

@dp.callback_query(F.data == "fav")
async def show_fav(cb: CallbackQuery):
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT title, link, price FROM fav WHERE user=?", (cb.from_user.id,)
        ) as c:
            rows = await c.fetchall()

    if not rows:
        txt = "⭐ Favorin yok"
    else:
        txt = "⭐ Favorilerin:\n\n"
        for title, link, price in rows:
            txt += f"• **{title}**\n💰 {price}\n🔗 [Ürüne Git]({link})\n\n"

    await safe_edit_or_send(cb.message, txt, back_kb())
    await cb.answer()

# ====================== FİYAT TAKİP ======================
@dp.callback_query(F.data == "alerts")
async def show_alerts(cb: CallbackQuery):
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT title, link, current_price, target_price FROM alerts WHERE user=?", 
            (cb.from_user.id,)
        ) as c:
            rows = await c.fetchall()

    if not rows:
        txt = "👀 Henüz takip ettiğin ürün yok"
    else:
        txt = "👀 Takip Ettiğin Ürünler:\n\n"
        for title, link, current_price, target_price in rows:
            txt += f"• **{title}**\n💰 Şu an: {current_price}\n🎯 Hedef: {target_price} TL\n🔗 [Ürüne Git]({link})\n\n"

    await safe_edit_or_send(cb.message, txt, back_kb())
    await cb.answer()

@dp.callback_query(F.data.startswith("track:"))
async def track_product(cb: CallbackQuery, state: FSMContext):
    i = int(cb.data.split(":")[1])
    p = CACHE[cb.from_user.id]["data"][i]
    await state.update_data(p=p)
    await cb.message.answer("🎯 Hedef fiyat girin (TL):")
    await state.set_state(States.target_price)
    await cb.answer()

@dp.message(States.target_price)
async def set_target_price(m: Message, state: FSMContext):
    try:
        target = float(m.text)
    except:
        await m.answer("❌ Geçerli bir sayı girin.")
        return

    data = await state.get_data()
    p = data.get("p")

    async with aiosqlite.connect(DB) as db:
        try:
            await db.execute(
                "INSERT INTO alerts (user, link, title, current_price, target_price) VALUES (?, ?, ?, ?, ?)",
                (m.from_user.id, p.get("link"), p.get("title"), p.get("price"), target)
            )
            await db.commit()
            await m.answer(f"✅ Takip başlatıldı!\nÜrün: {p.get('title')}\nHedef: {target} TL")
        except:
            await m.answer("❌ Bu ürün zaten takipte.")

    await state.clear()

# ====================== PREMIUM & ADMIN ======================
@dp.callback_query(F.data == "premium")
async def premium_request(cb: CallbackQuery):
    if await is_premium(cb.from_user.id):
        await cb.answer("Zaten premium'sun!")
        return

    code = ref_code(cb.from_user.id)
    text = f"""💰 **Reklamları Kaldır (Premium)**

Ücret: 45 TL

IBAN:
`{IBAN}`

Referans Kodun:
`{code}`

Ödeme yaptıktan sonra admin onaylayacak."""

    await safe_edit_or_send(cb.message, text)
    await cb.answer()

@dp.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery):
    await cb.answer("Zaten premium üyesiniz!")

# Admin Reklam Gönderme
@dp.callback_query(F.data == "ad")
async def ad_start(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("⛔ Yetkiniz yok!", show_alert=True)
        return
    await state.set_state(States.ad_text)
    await safe_edit_or_send(cb.message, "📢 **Reklam Gönder**\n\nGöndermek istediğiniz mesajı yazın:\n(İptal için /cancel yazın)")
    await cb.answer()

@dp.message(States.ad_text)
async def ad_send(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        await m.answer("⛔ Yetkiniz yok!")
        await state.clear()
        return

    if m.text.strip() == "/cancel":
        await m.answer("❌ İptal edildi.", reply_markup=back_kb())
        await state.clear()
        return

    reklam_metni = m.text.strip()
    await m.answer("📤 Reklam gönderiliyor...")

    sent = 0
    failed = 0

    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT id FROM users") as c:
            users = await c.fetchall()

    for (user_id,) in users:
        if await is_premium(user_id):
            continue
        try:
            await bot.send_message(user_id, f"📢 **Duyuru**\n\n{reklam_metni}", parse_mode="Markdown")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1

    await m.answer(
        f"✅ Reklam gönderimi tamamlandı!\n\nBaşarılı: {sent}\nBaşarısız: {failed}",
        reply_markup=back_kb()
    )
    await state.clear()

# Admin Premium Onay
@dp.callback_query(F.data == "approve")
async def approve_start(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("⛔ Yetkiniz yok!", show_alert=True)
        return
    await state.set_state(States.approve_code)
    await safe_edit_or_send(cb.message, "💳 **Premium Onay**\n\nOnaylanacak referans kodunu girin:\n(İptal için /cancel yazın)")
    await cb.answer()

@dp.message(States.approve_code)
async def approve_premium(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        await m.answer("⛔ Yetkiniz yok!")
        await state.clear()
        return

    if m.text.strip() == "/cancel":
        await m.answer("❌ İptal edildi.", reply_markup=back_kb())
        await state.clear()
        return

    code = m.text.strip()
    try:
        parts = code.split("-")
        if len(parts) >= 3 and parts[0] == "PREM":
            uid = int(parts[1])
        else:
            await m.answer("❌ Geçersiz kod formatı!", reply_markup=back_kb())
            await state.clear()
            return
    except:
        await m.answer("❌ Kod okunamadı.", reply_markup=back_kb())
        await state.clear()
        return

    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO premium VALUES (?)", (uid,))
        await db.commit()

    try:
        await bot.send_message(uid, "🎉 **Tebrikler!** Premium üyeliğiniz aktif edildi!")
    except:
        pass

    await m.answer(f"✅ Kullanıcı {uid} premium yapıldı!", reply_markup=back_kb())
    await state.clear()

# ====================== MAIN ======================
async def main():
    await init_db()
    print("🚀 FiyatAvcısıBot çalışıyor...")
    print(f"Admin ID: {ADMIN_ID}")
    asyncio.create_task(check_price_drops())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())