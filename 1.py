import asyncio
import feedparser
import requests
import logging
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

import os

# --- SOZLAMALAR ---
TOKEN = os.getenv("BOT_TOKEN")
RSS_URL = "https://kun.uz/uz/news/rss"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Global o'zgaruvchilar
news_list = []
subscribers = set() 
processed_news = set() 

def get_news_page(page: int = 0):
    """Ma'lum bir sahifadagi yangiliklarni chiqarish uchun helper"""
    items_per_page = 10
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    
    current_news = news_list[start_idx:end_idx]
    
    if not current_news:
        return None, None

    builder = InlineKeyboardBuilder()
    text = f"<b>Eng so'nggi yangiliklar ro'yxati ({start_idx + 1}-{min(end_idx, len(news_list))}):</b>\n\n"
    
    # Raqamli tugmalar
    for i, entry in enumerate(current_news):
        actual_index = start_idx + i
        text += f"{actual_index + 1}. {entry.title}\n\n"
        builder.button(text=f"{actual_index + 1}", callback_data=f"news_{actual_index}")
    
    builder.adjust(5) # Raqamlarni 5 tadan qilib teramiz
    
    # Navigatsiya tugmalari (Pastki qatorda)
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton(text="<< Oldingi", callback_data=f"page_{page-1}"))
    if end_idx < len(news_list):
        nav_buttons.append(types.InlineKeyboardButton(text="Keyingi >>", callback_data=f"page_{page+1}"))
    
    if nav_buttons:
        builder.row(*nav_buttons)
        
    return text, builder.as_markup()

def get_full_text(url):
    """Maqola matnini olishning eng ishonchli yo'li"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36'}
        res = requests.get(url, headers=headers, timeout=10)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Kun.uz'da matn asosan 'single-content' yoki 'page-text' ichida bo'ladi
        # Biz barcha ehtimollarni tekshiramiz
        target = soup.find('div', class_='single-content') or \
                 soup.find('div', class_='page-text') or \
                 soup.find('main')
        
        if target:
            paragraphs = target.find_all('p')
            # 30 tadan ko'p harfi bor paragraflarni olamiz (reklamalarni chetlatish uchun)
            text = "\n\n".join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 30])
            if text:
                return text[:3800] # Telegram limiti
                
        return "Kechirasiz, ushbu maqola matnini hozircha o'qib bo'lmadi. Sayt strukturasi o'zgargan bo'lishi mumkin."
    except Exception as e:
        return f"Xatolik yuz berdi: {e}"

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    global news_list
    subscribers.add(message.chat.id)
    
    msg = await message.answer("🔄 <i>Yangiliklar yuklanmoqda...</i>")
    
    feed = feedparser.parse(RSS_URL)
    news_list = feed.entries[:50] # 50 ta yangilikni yuklaymiz
    
    for entry in news_list:
        processed_news.add(entry.link)
    
    if not news_list:
        await msg.edit_text("Yangiliklar topilmadi.")
        return

    text, reply_markup = get_news_page(0)
    await msg.edit_text(text, reply_markup=reply_markup)

@dp.callback_query(F.data.startswith("page_"))
async def handle_pagination(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[1])
    text, reply_markup = get_news_page(page)
    
    if text:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    await callback.answer()

@dp.callback_query(F.data.startswith("news_"))
async def show_news_detail(callback: types.CallbackQuery):
    index = int(callback.data.split("_")[1])
    entry = news_list[index]
    
    await callback.message.answer(f"⏳ <b>{entry.title}</b>\n<i>Matn tayyorlanmoqda...</i>")
    
    full_text = get_full_text(entry.link)
    
    final_msg = (
        f"<b>🔴 {entry.title}</b>\n\n"
        f"{full_text}\n\n"
        f"🔗 <a href='{entry.link}'>Asl manba</a>"
    )
    
    await callback.message.answer(final_msg, disable_web_page_preview=True)
    await callback.answer() # Tugma bosilgandagi "soat" belgisini yo'qotish

async def monitor_news():
    """Yangi yangiliklarni tekshirib turuvchi funksiya"""
    while True:
        try:
            feed = feedparser.parse(RSS_URL)
            for entry in feed.entries[:5]: # Oxirgi 5 tasini tekshiramiz
                if entry.link not in processed_news:
                    processed_news.add(entry.link)
                    
                    # Yangi xabar haqida barcha obunachilarga bildirishnoma yuborish
                    msg_text = (
                        f"✨ <b>YANGI XABAR CHIQDI!</b>\n\n"
                        f"🔴 {entry.title}\n\n"
                        f"🔄 <i>Yangi yangiliklarni ko'rish uchun /start bosing.</i>"
                    )
                    
                    for user_id in subscribers:
                        try:
                            await bot.send_message(user_id, msg_text)
                        except Exception as e:
                            logging.error(f"Xabar yuborishda xato ({user_id}): {e}")
            
        except Exception as e:
            logging.error(f"Monitoringda xato: {e}")
        
        await asyncio.sleep(300) # 5 daqiqa (300 soniya) kutish

async def main():
    print("Bot tugmalar bilan ishga tushdi...")
    # Monitoringni alohida task sifatida ishga tushiramiz
    asyncio.create_task(monitor_news())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())