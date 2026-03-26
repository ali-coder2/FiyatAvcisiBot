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
import re

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
    ad = State()
    approve = State()

# ========== DB ==========

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
            UNIQUE(user, link)
        )""")
        await db.commit()

# ========== HELPERS ==========

def ref_code(uid):
    return f"PREM-{uid}-" + ''.join(random.choices(string.ascii_uppercase, k=5))

async def is_premium(uid):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT 1 FROM premium WHERE id=?", (uid,)) as c:
            return await c.fetchone() is not None

def extract_price(price_str):
    """Fiyat stringinden sayı çıkar"""
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
        params["price_min"] = str(int(min_p))
    if max_p is not None:
        params["price_max"] = str(int(max_p))

    print(f"API Çağrısı: {params}")
    
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, lambda: GoogleSearch(params).get_dict())
        
        shopping_results = result.get("shopping_results", [])
        if not shopping_results:
            shopping_results = result.get("inline_shopping_results", [])
        if not shopping_results:
            shopping_results = result.get("sponsored_results", [])
            
        print(f"Bulunan sonuç sayısı: {len(shopping_results)}")
        
        normalized_results = []
        for item in shopping_results:
            normalized_item = {
                "title": item.get("title", item.get("name", "Başlık yok")),
                "price": item.get("price", item.get("extracted_price", "Fiyat yok")),
                "link": item.get("link", item.get("product_link", "#")),
                "thumbnail": item.get("thumbnail", item.get("image", None)),
                "source": item.get("source", item.get("merchant", "Bilinmeyen"))
            }
            normalized_results.append(normalized_item)
            
        return {"shopping_results": normalized_results}
        
    except Exception as e:
        print(f"API Hatası: {e}")
        import traceback
        traceback.print_exc()
        return {"shopping_results": []}

# ========== FİYAT KONTROLÜ (SCHEDULER) ==========

async def check_price_drops():
    """Belirli aralıklarla takipteki ürünlerin fiyatlarını kontrol et"""
    while True:
        try:
            async with aiosqlite.connect(DB) as db:
                async with db.execute("SELECT user, link, title, current_price, target_price FROM alerts") as c:
                    alerts = await c.fetchall()
            
            for alert in alerts:
                user_id, link, title, old_price_str, target_price = alert
                
                # Ürünü tekrar ara
                res = await search(title)
                items = res.get("shopping_results", [])
                
                # Aynı linki bul
                current_item = None
                for item in items:
                    if item.get("link") == link:
                        current_item = item
                        break
                
                if current_item:
                    current_price_str = current_item.get("price", "Fiyat yok")
                    current_price_val = extract_price(current_price_str)
                    
                    # Veritabanını güncelle
                    async with aiosqlite.connect(DB) as db:
                        await db.execute(
                            "UPDATE alerts SET current_price = ? WHERE user = ? AND link = ?",
                            (current_price_str, user_id, link)
                        )
                        await db.commit()
                    
                    # Fiyat hedefin altına düştü mü?
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
                                parse_mode="Markdown"
                            )
                            # Bildirim gönderildi, takipten çıkar
                            async with aiosqlite.connect(DB) as db:
                                await db.execute(
                                    "DELETE FROM alerts WHERE user = ? AND link = ?",
                                    (user_id, link)
                                )
                                await db.commit()
                        except:
                            pass
            
            # 30 dakika bekle
            await asyncio.sleep(1800)
            
        except Exception as e:
            print(f"Fiyat kontrol hatası: {e}")
            await asyncio.sleep(300)

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
        kb.append([InlineKeyboardButton(text="✅ Premium Aktif", callback_data="noop")])
    if admin:
        kb.append([InlineKeyboardButton(text="📢 Reklam Gönder", callback_data="ad")])
        kb.append([InlineKeyboardButton(text="💳 Premium Onayla", callback_data="approve")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def product_kb(i, total, link):
    keyboard = []
    
    keyboard.append([InlineKeyboardButton(text="🔗 Ürüne Git", url=link)])
    
    keyboard.append([
        InlineKeyboardButton(text="⭐ Favori", callback_data=f"fav_add:{i}"),
        InlineKeyboardButton(text="🔔 Takip", callback_data=f"track:{i}")
    ])
    
    nav_row = []
    if i > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Önceki", callback_data="prev"))
    if i < total - 1:
        nav_row.append(InlineKeyboardButton(text="Sonraki ➡️", callback_data="next"))
    
    if nav_row:
        keyboard.append(nav_row)
    
    keyboard.append([InlineKeyboardButton(text="🔙 Ana Menü", callback_data="menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Ana Menü", callback_data="menu")]
    ])

def budget_choice_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Bütçe Belirle", callback_data="budget")],
        [InlineKeyboardButton(text="🚀 Filtresiz Ara", callback_data="nofilter")]
    ])

# ========== SHOW ==========

async def show_product(message, uid, is_callback=False):
    """Ürün göster - fotoğraf varsa silip yeni gönder, yoksa edit et"""
    data = CACHE.get(uid)
    if not data or not data["data"]:
        if is_callback:
            await message.edit_text("❌ Ürün verisi bulunamadı.", reply_markup=back_kb())
        else:
            await message.answer("❌ Ürün verisi bulunamadı.", reply_markup=back_kb())
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
    source = p.get("source", "Bilinmeyen kaynak")

    text = f"📦 **{title}**\n\n💰 {price}\n🏪 {source}\n\n🔗 [Ürüne Git]({link})"

    markup = product_kb(i, len(data["data"]), link)

    try:
        if img:
            # Fotoğraf varsa her zaman silip yeni gönder (edit edilemez çünkü)
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
            # Fotoğraf yoksa edit et
            if is_callback:
                await message.edit_text(text, parse_mode="Markdown", reply_markup=markup)
            else:
                await message.answer(text, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        print(f"Show hatası: {e}")
        try:
            await message.answer(text, parse_mode="Markdown", reply_markup=markup)
        except:
            pass

# ========== START ==========

@dp.message(Command("start"))
async def start(m: Message, state: FSMContext):
    await state.clear()
    
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
        await db.commit()

    prem = await is_premium(m.from_user.id)
    await m.answer(
        "👋 Hoş geldin! Aşağıdaki menüden işlem seçebilirsin.",
        reply_markup=menu_kb(prem, m.from_user.id == ADMIN_ID)
    )

# ========== MENU ==========

@dp.callback_query(F.data == "menu")
async def menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    prem = await is_premium(cb.from_user.id)
    
    await cb.message.edit_text(
        "📋 Ana Menü - İşlem seçin:",
        reply_markup=menu_kb(prem, cb.from_user.id == ADMIN_ID)
    )
    await cb.answer()

# ========== SEARCH FLOW ==========

@dp.callback_query(F.data == "search")
async def s(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("🔍 Hangi ürünü aramak istiyorsun?\n\nÜrün adını yazın:")
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
        await cb.message.edit_text("❌ Önce ürün adı yazmalısınız.", reply_markup=back_kb())
        await state.clear()
        await cb.answer()
        return

    if cb.data == "budget":
        await cb.message.edit_text("💰 Minimum fiyat (TL) girin:")
        await state.set_state(States.min_price)
    else:
        await cb.message.edit_text("🔍 Aranıyor... Lütfen bekleyin.")
        
        res = await search(query)
        items = res.get("shopping_results", [])
        
        print(f"Filtresiz arama: {query} - {len(items)} sonuç")
        
        if not items:
            await cb.message.edit_text("❌ Aradığınız ürün bulunamadı.", reply_markup=back_kb())
            await state.clear()
            await cb.answer()
            return
        
        CACHE[cb.from_user.id] = {"data": items, "i": 0}
        # İlk gösterim - callback mesajı üzerinden
        await show_product(cb.message, cb.from_user.id, is_callback=True)
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
    await m.answer("💰 Maksimum fiyat (TL) girin:")
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
        await m.answer("❌ Bir hata oluştu. /start ile yeniden başlayın.")
        await state.clear()
        return
    
    loading_msg = await m.answer("🔍 Aranıyor... Lütfen bekleyin.")
    
    res = await search(query, min_val, val)
    items = res.get("shopping_results", [])
    
    print(f"Filtreli arama: {query} (min:{min_val}, max:{val}) - {len(items)} sonuç")
    
    if not items:
        await loading_msg.edit_text("❌ Aradığınız ürün bulunamadı.", reply_markup=back_kb())
        await state.clear()
        return

    CACHE[m.from_user.id] = {"data": items, "i": 0}
    
    # İlk gösterim - normal mesaj
    await show_product(loading_msg, m.from_user.id, is_callback=False)
    await state.clear()

# ========== NAV ==========

@dp.callback_query(F.data.in_(["next", "prev"]))
async def nav(cb: CallbackQuery):
    c = CACHE.get(cb.from_user.id)
    if not c or not c["data"]:
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
    
    # Her zaman silip yeni gönder (fotoğraf varsa edit edilemez)
    await show_product(cb.message, cb.from_user.id, is_callback=True)
    await cb.answer()

# ========== FAVORİ ==========

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
            await cb.answer("✅ Favorilere eklendi")
        except:
            await cb.answer("❌ Zaten favorilerde")

@dp.callback_query(F.data == "fav")
async def fav(cb: CallbackQuery):
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT title, link, price FROM fav WHERE user=?", 
            (cb.from_user.id,)
        ) as c:
            rows = await c.fetchall()

    if not rows:
        txt = "⭐ Favorin yok"
    else:
        txt = "⭐ Favorilerin:\n\n"
        for idx, row in enumerate(rows, 1):
            title, link, price = row
            txt += f"{idx}. **{title}**\n💰 {price}\n🔗 [Ürüne Git]({link})\n\n"
    
    await cb.message.edit_text(txt, parse_mode="Markdown", reply_markup=back_kb())
    await cb.answer()

# ========== TAKİPLER ==========

@dp.callback_query(F.data == "alerts")
async def alerts(cb: CallbackQuery):
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT title, link, current_price, target_price FROM alerts WHERE user=?", 
            (cb.from_user.id,)
        ) as c:
            rows = await c.fetchall()

    if not rows:
        txt = "📊 Takip ettiğin ürün yok"
    else:
        txt = "📊 Takip Ettiğin Ürünler:\n\n"
        for idx, row in enumerate(rows, 1):
            title, link, current_price, target_price = row
            txt += (f"{idx}. **{title}**\n"
                   f"💰 Şu anki: {current_price}\n"
                   f"🎯 Hedef: {target_price} TL\n"
                   f"🔗 [Ürüne Git]({link})\n\n")
    
    await cb.message.edit_text(txt, parse_mode="Markdown", reply_markup=back_kb())
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
        target_price = float(m.text)
    except:
        await m.answer("❌ Lütfen geçerli bir sayı girin.")
        return

    data = await state.get_data()
    p = data.get("p")

    async with aiosqlite.connect(DB) as db:
        try:
            await db.execute(
                "INSERT INTO alerts (user, link, title, current_price, target_price) VALUES (?, ?, ?, ?, ?)",
                (m.from_user.id, p.get("link"), p.get("title"), p.get("price"), target_price)
            )
            await db.commit()
            await m.answer(f"✅ Takip başlatıldı!\n\nÜrün: {p.get('title')}\nHedef: {target_price} TL")
        except:
            await m.answer("❌ Bu ürün zaten takipte")

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

@dp.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery):
    await cb.answer("Zaten premium üyesiniz!")

# ========== ADMIN - REKLAM ==========

@dp.message(States.ad)
async def ad_send(m: Message, state: FSMContext):
    """Reklam mesajını tüm kullanıcılara gönder"""
    print(f"Ad_send çağrıldı - User: {m.from_user.id}, Text: {m.text}")
    
    # Admin kontrolü
    if m.from_user.id != ADMIN_ID:
        await m.answer("⛔ Yetkiniz yok!")
        await state.clear()
        return
    
    # İptal kontrolü
    if m.text and m.text.strip() == "/cancel":
        await m.answer("❌ İptal edildi.", reply_markup=back_kb())
        await state.clear()
        return
    
    # Mesaj boş mu kontrolü
    if not m.text or not m.text.strip():
        await m.answer("❌ Boş mesaj gönderilemez. Lütfen bir mesaj yazın veya /cancel ile iptal edin.")
        return
    
    reklam_metni = m.text.strip()
    
    # Kullanıcıları al
    try:
        async with aiosqlite.connect(DB) as db:
            async with db.execute("SELECT id FROM users") as c:
                users = await c.fetchall()
        
        print(f"Toplam kullanıcı: {len(users)}")
        
        if not users:
            await m.answer("❌ Hiç kullanıcı bulunamadı.", reply_markup=back_kb())
            await state.clear()
            return
        
    except Exception as e:
        print(f"DB hatası: {e}")
        await m.answer(f"❌ Veritabanı hatası: {e}", reply_markup=back_kb())
        await state.clear()
        return
    
    # Gönderim işlemi
    await m.answer("📤 Gönderiliyor... Lütfen bekleyin.")
    
    sent = 0
    failed = 0
    failed_users = []
    
    for user_row in users:
        user_id = user_row[0]
        try:
            await bot.send_message(
                user_id, 
                f"📢 **Duyuru**\n\n{reklam_metni}", 
                parse_mode="Markdown"
            )
            sent += 1
            print(f"Gönderildi: {user_id}")
            # Rate limit için küçük bekleme
            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1
            failed_users.append(user_id)
            print(f"Gönderilemedi: {user_id} - {e}")
    
    # Sonuç mesajı
    result_text = (
        f"✅ **Gönderim Tamamlandı**\n\n"
        f"📤 Başarılı: {sent}\n"
        f"❌ Başarısız: {failed}\n"
        f"👥 Toplam: {len(users)}"
    )
    
    if failed > 0 and len(failed_users) <= 5:
        result_text += f"\n\nBaşarısız ID'ler: {', '.join(map(str, failed_users))}"
    
    await m.answer(result_text, reply_markup=back_kb())
    await state.clear()
    print(f"Reklam gönderimi tamamlandı - Başarılı: {sent}, Başarısız: {failed}")

# ========== ADMIN - ONAY ==========

@dp.callback_query(F.data == "approve")
async def approve_start(cb: CallbackQuery, state: FSMContext):
    """Premium onay başlat"""
    print(f"Approve callback çağrıldı - User: {cb.from_user.id}")
    
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("⛔ Yetkiniz yok!", show_alert=True)
        return
    
    await state.clear()
    
    try:
        await cb.message.edit_text(
            "💳 **Premium Onay**\n\n"
            "Onaylanacak referans kodunu girin:\n"
            "(İptal için /cancel yazın)",
            parse_mode="Markdown"
        )
        await state.set_state(States.approve)
        await cb.answer("Onay modu aktif")
    except Exception as e:
        print(f"Approve start hatası: {e}")
        await cb.answer("Hata oluştu")

@dp.message(States.approve)
async def approve_premium(m: Message, state: FSMContext):
    """Premium onayla"""
    print(f"Approve_premium çağrıldı - User: {m.from_user.id}, Text: {m.text}")
    
    # Admin kontrolü
    if m.from_user.id != ADMIN_ID:
        await m.answer("⛔ Yetkiniz yok!")
        await state.clear()
        return
    
    # İptal kontrolü
    if m.text and m.text.strip() == "/cancel":
        await m.answer("❌ İptal edildi.", reply_markup=back_kb())
        await state.clear()
        return
    
    code = m.text.strip()
    
    # Kod formatı: PREM-{uid}-XXXXX
    try:
        parts = code.split("-")
        if len(parts) >= 3 and parts[0] == "PREM":
            uid = int(parts[1])
        else:
            await m.answer("❌ Geçersiz referans kodu formatı.\n\nÖrnek: PREM-12345-ABCDE", reply_markup=back_kb())
            await state.clear()
            return
    except ValueError as e:
        print(f"Kod parse hatası: {e}")
        await m.answer("❌ Geçersiz referans kodu formatı.", reply_markup=back_kb())
        await state.clear()
        return
    
    # Premium ekle
    try:
        async with aiosqlite.connect(DB) as db:
            await db.execute("INSERT OR IGNORE INTO premium VALUES (?)", (uid,))
            await db.commit()
        
        # Kullanıcıya bildir
        try:
            await bot.send_message(uid, "🎉 **Tebrikler!**\n\nPremium üyeliğiniz aktif edildi. Artık reklamsız kullanabilirsiniz!")
            bildirim = "✅ Kullanıcıya bildirim gönderildi."
        except Exception as e:
            print(f"Bildirim hatası: {e}")
            bildirim = "⚠️ Kullanıcıya bildirim gönderilemedi (botu engellemiş olabilir)."
        
        await m.answer(f"✅ Kullanıcı `{uid}` premium yapıldı.\n\n{bildirim}", reply_markup=back_kb())
        
    except Exception as e:
        print(f"DB hatası: {e}")
        await m.answer(f"❌ Veritabanı hatası: {e}", reply_markup=back_kb())
    
    await state.clear()

# ========== MAIN ==========

async def main():
    await init_db()
    print("🤖 Bot başlatılıyor...")
    print(f"Admin ID: {ADMIN_ID}")
    
    # Fiyat kontrol task'ını başlat
    asyncio.create_task(check_price_drops())
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
