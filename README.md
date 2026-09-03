# 🛍️ FiyatAvcisiBot

SerpApi Google Shopping altyapısını kullanan, anlık ürün araması yapabilen ve hedef fiyatlara göre otomatik takip gerçekleştiren modern bir Telegram botu.

## ✨ Özellikler

* **Google Shopping Entegrasyonu:** Güncel ürün, fiyat, satıcı ve görsel bilgilerine ulaşın.
* **Akıllı Fiyat Takibi:** Hedef fiyat belirleyin, fiyat düştüğünde bildirim alın.
* **Gelişmiş Arama:** Filtresiz arama yapın veya bütçe aralığı belirleyin.
* **Favoriler Sistemi:** Ürünleri favorilere ekleyin ve tek tuşla listeleyin.
* **Admin Paneli:** Toplu duyuru gönderin ve ödemeleri onaylayarak Premium'u aktif edin.
* **Asenkron Altyapı:** Aiogram 3 ve aiosqlite ile hızlı ve kesintisiz çalışma.

---

## 🛠️ Kullanılan Teknolojiler

* Python (3.10+)
* Aiogram 3.x
* SerpApi (Google Shopping API)
* aiosqlite
* python-dotenv

---

## 🚀 Kurulum ve Çalıştırma

Terminalde sırasıyla şu komutları çalıştırın:

```bash
git clone [https://github.com/ali-coder2/FiyatAvcisiBot.git](https://github.com/ali-coder2/FiyatAvcisiBot.git)
cd FiyatAvcisiBot
pip install -r requirements.txt
python bot.py
