# Telegram Google Alışveriş ve Fiyat Takip Botu

Bu proje, SerpApi Google Shopping altyapısını kullanarak anlık ürün araması yapabilen ve kullanıcıların belirledikleri hedef fiyatlara göre arka planda otomatik fiyat takibi gerçekleştiren modern bir Telegram botudur.

## 🚀 Özellikler

* **Google Shopping Entegrasyonu:** SerpApi kullanarak en güncel ürün, fiyat, satıcı ve görsel bilgilerine ulaşırsınız.
* **Akıllı Fiyat Takibi:** Beğendiğiniz ürünler için hedef fiyat belirleyebilir; arka plandaki asenkron döngü sayesinde fiyat düştüğünde anında bildirim alırsınız.
* **Gelişmiş Arama ve Filtreleme:** Filtresiz arama yapabilir veya minimum/maksimum bütçe aralığı belirleyebilirsiniz.
* **Favoriler Sistemi:** İlginizi çeken ürünleri favorilerinize ekleyebilir ve tek tuşla listeleyebilirsiniz.
* **Admin Paneli & Duyurular:** Tüm kullanıcılara toplu reklam/duyuru mesajı gönderebilir, IBAN ile yapılan ödemeleri referans kodları üzerinden onaylayarak Premium üyeliği aktif edebilirsiniz.
* **Modern Altyapı:** Aiogram 3 ve `aiosqlite` kullanılarak tamamen asenkron (non-blocking) olarak geliştirilmiştir.

---

## 🛠️ Kullanılan Teknolojiler

* **Python** (3.10 veya üzeri)
* **Aiogram 3.x** (Asenkron Telegram Bot Kütüphanesi)
* **SerpApi** (Google Shopping API)
* **aiosqlite** (Asenkron SQLite Veritabanı Yönetimi)
* **python-dotenv** (Çevresel Değişken Yönetimi)

---

## ⚙️ Kurulum ve Çalıştırma

Projeyi yerel bilgisayarınızda veya sunucunuzda çalıştırmak için aşağıdaki adımları takip edebilirsiniz:

### 1. Projeyi Klonlayın
```bash
git clone https://github.com/kullaniciadiniz/proje-adi.git
cd proje-adi
