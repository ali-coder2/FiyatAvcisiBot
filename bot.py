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
CACHE = {}  # Kullanıcı bazlı arama cache

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

# ====================== FİYAT TAKİP SCHEDULER ======================
async def check_price_drops():
    """Her 30 dakikada bir takip edilen ürünlerin fiyatlarını kontrol eder"""
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

                        # Fiyatı güncelle
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
                                # Takibi sil
                                async with aiosqlite.connect(DB) as db:
                                    await db.execute("DELETE FROM alerts WHERE user = ? AND link = ?", (user_id, link))
                                    await db.commit()
                            except Exception as e:
                                print(f"Bildirim gönderme hatası: {e}")
                        break

            await asyncio.sleep(1800)  # 30 dakika

        except Exception as e:
            print(f"Fiyat takip scheduler hatası: {e}")
            await asyncio.sleep(300)

# ====================== SEARCH ======================
async def search(q, min_p=None, max_p=None):
    params = {
        "api_key": SERPAPI_KEY,
        "engine": "google_shopping",
        "q": q,
        "hl": "tr",
        "gl": "tr",
        "num": 8
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
        for item in shopping[:6]:
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
    await cb.message.edit_text(
        "📋 Ana Menü - İşlem seçin:",
        reply_markup=menu_kb(prem, cb.from_user.id == ADMIN_ID)
    )
    await cb.answer()

# ====================== ARA ======================
@dp.callback_query(F.data == "search")
async def search_start(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await cb.message.edit_text("🔍 Hangi ürünü aramak istiyorsun?\nÜrün adını yazın:")
    except:
        await cb.message.delete()
        await cb.message.answer("🔍 Hangi ürünü aramak istiyorsun?\nÜrün adını yazın:")
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
        await cb.message.edit_text("❌ Önce ürün adı yazmalısınız.", reply_markup=back_kb())
        await state.clear()
        await cb.answer()
        return

    if cb.data == "budget":
        await cb.message.edit_text("💰 Minimum fiyat (TL) girin:")
        await state.set_state(States.min_price)
    else:
        await cb.message.edit_text("🔍 Aranıyor...")
        res = await search(query)
        items = res.get("shopping_results", [])
        if not items:
            await cb.message.edit_text("❌ Sonuç bulunamadı.", reply_markup=back_kb())
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

    await m.answer("🔍 Aranıyor...")
    res = await search(query, min_val, val)
    items = res.get("shopping_results", [])

    if not items:
        await m.answer("❌ Sonuç bulunamadı.", reply_markup=back_kb())
        await state.clear()
        return

    CACHE[m.from_user.id] = {"data": items, "i": 0}
    await show_product(m, m.from_user.id, is_callback=False)
    await state.clear()

# ====================== ÜRÜN GÖSTERME ======================
async def show_product(message, uid, is_callback=False):
    data = CACHE.get(uid)
    if not data or not data["data"]:
        text = "❌ Ürün verisi bulunamadı."
        if is_callback:
            await message.edit_text(text, reply_markup=back_kb())
        else:
            await message.answer(text, reply_markup=back_kb())
        return

    i = data["i"]
    p = data["data"][i]

    title = p.get("title", "Başlık yok")
    price = p.get("price", "Fiyat yok")
    link = p.get("link", "#")
    img = p.get("thumbnail")
    source = p.get("source", "Bilinmeyen")

    text = f"📦 **{title}**\n\n💰 {price}\n🏪 {source}\n\n🔗 [Ürüne Git]({link})"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Ürüne Git", url=link)],
        [
            InlineKeyboardButton(text="⭐ Favori", callback_data=f"fav_add:{i}"),
            InlineKeyboardButton(text="🔔 Takip Et", callback_data=f"track:{i}")
        ],
        [InlineKeyboardButton(text="🔙 Ana Menü", callback_data="menu")]
    ])

    if img:
        if is_callback:
            try:
                await message.delete()
            except:
                pass
        await message.answer_photo(photo=img, caption=text, parse_mode="Markdown", reply_markup=kb)
    else:
        if is_callback:
            await message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        else:
            await message.answer(text, parse_mode="Markdown", reply_markup=kb)

# ====================== NAVİGASYON ======================
@dp.callback_query(F.data.in_(["next", "prev"]))
async def nav(cb: CallbackQuery):
    c = CACHE.get(cb.from_user.id)
    if not c:
        await cb.answer("Veri yok")
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

    try:
        await cb.message.edit_text(txt, parse_mode="Markdown", reply_markup=back_kb())
    except:
        await cb.message.delete()
        await cb.message.answer(txt, parse_mode="Markdown", reply_markup=back_kb())
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

    try:
        await cb.message.edit_text(txt, parse_mode="Markdown", reply_markup=back_kb())
    except:
        await cb.message.delete()
        await cb.message.answer(txt, parse_mode="Markdown", reply_markup=back_kb())
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

# ====================== PREMIUM ======================
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

    try:
        await cb.message.edit_text(text, parse_mode="Markdown")
    except:
        await cb.message.delete()
        await cb.message.answer(text, parse_mode="Markdown")
    await cb.answer()

@dp.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery):
    await cb.answer("Zaten premium üyesiniz!")

# ====================== ADMIN - REKLAM ======================
@dp.callback_query(F.data == "ad")
async def ad_start(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("⛔ Yetkiniz yok!", show_alert=True)
        return

    await state.set_state(States.ad_text)
    await cb.message.edit_text(
        "📢 **Reklam Gönder**\n\nGöndermek istediğiniz mesajı yazın:\n(İptal için /cancel yazın)",
        parse_mode="Markdown"
    )
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
            continue  # Premium kullanıcılara reklam gönderme
        try:
            await bot.send_message(user_id, f"📢 **Duyuru**\n\n{reklam_metni}", parse_mode="Markdown")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1

    await m.answer(
        f"✅ Reklam gönderimi tamamlandı!\n\n"
        f"Başarılı: {sent}\n"
        f"Başarısız: {failed}",
        reply_markup=back_kb()
    )
    await state.clear()

# ====================== ADMIN - PREMIUM ONAY ======================
@dp.callback_query(F.data == "approve")
async def approve_start(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("⛔ Yetkiniz yok!", show_alert=True)
        return

    await state.set_state(States.approve_code)
    await cb.message.edit_text(
        "💳 **Premium Onay**\n\nOnaylanacak referans kodunu girin:\n(İptal için /cancel yazın)",
        parse_mode="Markdown"
    )
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