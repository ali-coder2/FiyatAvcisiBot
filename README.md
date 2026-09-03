FiyatAvcisiBot 🛍️ - Telegram Google Alışveriş ve Fiyat Takip Botu 🤖

Bu proje, SerpApi Google Shopping altyapısını kullanarak anlık ürün araması yapabilen ve kullanıcıların belirledikleri hedef fiyatlara göre arka planda otomatik fiyat takibi gerçekleştiren modern bir Telegram botudur. Proje deposu: https://github.com/ali-coder2/FiyatAvcisiBot

Özellikler ✨

- Google Shopping Entegrasyonu sayesinde en güncel ürün, fiyat, satıcı ve görsel bilgilerine ulaşırsınız. 🛒
- Akıllı Fiyat Takibi ile beğendiğiniz ürünler için hedef fiyat belirleyebilir, arka plandaki asenkron döngü sayesinde fiyat düştüğünde anında bildirim alırsınız. 🎯
- Gelişmiş arama ve filtreleme seçenekleriyle filtresiz arama yapabilir veya minimum/maksimum bütçe aralığı belirleyebilirsiniz. 🔍
- Favoriler sistemi üzerinden ilginizi çeken ürünleri favorilerinize ekleyebilir ve tek tuşla listeleyebilirsiniz. ⭐
- Admin paneli ve duyurular yardımıyla tüm kullanıcılara toplu reklam/duyuru mesajı gönderebilir, IBAN ile yapılan ödemeleri referans kodları üzerinden onaylayarak Premium üyeliği aktif edebilirsiniz. 💳
- Modern altyapısı sayesinde Aiogram 3 ve aiosqlite kullanılarak tamamen asenkron olarak geliştirilmiştir. ⚡

Kullanılan Teknolojiler 🛠️

- Python (3.10 veya üzeri) 🐍
- Aiogram 3.x (Asenkron Telegram Bot Kütüphanesi) 📦
- SerpApi (Google Shopping API) 🌐
- aiosqlite (Asenkron SQLite Veritabanı Yönetimi) 🗄️
- python-dotenv (Çevresel Değişken Yönetimi) ⚙️

Kurulum ve Çalıştırma 🚀

Projeyi yerel bilgisayarınızda veya sunucunuzda çalıştırmak için aşağıdaki adımları sırasıyla uygulayabilirsiniz:

- Terminal veya komut satırını açarak git clone https://github.com/ali-coder2/FiyatAvcisiBot.git komutu ile projeyi bilgisayarınıza indirin ve proje klasörüne girin. 💻
- İsteğe bağlı olarak python -m venv venv komutu ile bir sanal ortam oluşturun ve aktif hale getirin. 🧪
- Projenin bağımlılıklarını tek komutla yüklemek için pip install -r requirements.txt komutunu çalıştırın. 📦
- Ana dizinde .env adında bir dosya oluşturun (veya .env.example dosyasını kopyalayıp adını .env yapın) ve gerekli gizli bilgilerinizi eksiksiz bir şekilde doldurun. 📝
- python bot.py komutunu çalıştırarak botu aktif edin ve kullanmaya başlayın. ▶️

Proje Yapısı 📂

- bot.py: Ana bot mantığı, komut yönlendiricileri ve arka plan görevlerini barındırır.
- requirements.txt: Proje için gerekli Python kütüphane listesidir.
- .env.example: Çevresel değişkenler için örnek şablondur.
- .gitignore: Git tarafından takip edilmeyecek gereksiz dosya ve klasörleri tanımlar.
- Procfile: Sunucu dağıtımları için yapılandırma dosyasıdır.

Lisans 📄
Bu proje MIT lisansı altında açılmıştır. Dilediğiniz gibi geliştirebilir ve kullanabilirsiniz.
