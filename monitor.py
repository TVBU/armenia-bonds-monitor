#!/usr/bin/env python3
"""
Armenia Bonds Monitor
Мониторит новые размещения облигаций в Армении и отправляет уведомления в Telegram
"""

import requests
import json
import os
import re
import hashlib
from datetime import datetime
from bs4 import BeautifulSoup

# ============================================================
# НАСТРОЙКИ
# ============================================================
TELEGRAM_TOKEN = "8681090278:AAEAjCYJcx74pzrbU41w4LnHQI_fMmlRxUg"
CHAT_ID = "177924919"
SEEN_FILE = "seen_bonds.json"

# Минимальные купоны для уведомлений
MIN_COUPON_AMD = 9.0   # % для AMD облигаций
MIN_COUPON_USD = 8.0    # % для USD облигаций

# Источники для мониторинга
SOURCES = [
    {
        "name": "ArmBanks",
        "url": "https://armbanks.am/en/category/capital_market/",
        "base_url": "https://armbanks.am",
    },
    {
        "name": "Banks.am",
        "url": "https://banks.am/en/news/capital_market/",
        "base_url": "https://banks.am",
    },
    {
        "name": "ARKA",
        "url": "https://arka.am/en/news/business/",
        "base_url": "https://arka.am",
    },
]

# Ключевые слова для фильтрации статей об облигациях
BOND_KEYWORDS = [
    "bond", "bonds", "placement", "coupon", "maturity",
    "AMD bond", "USD bond", "issuance", "tranche"
]

# ============================================================
# TELEGRAM
# ============================================================
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

# ============================================================
# ХРАНЕНИЕ УЖЕ ВИДЕННЫХ СТАТЕЙ
# ============================================================
def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

def make_id(url):
    return hashlib.md5(url.encode()).hexdigest()

# ============================================================
# ПАРСИНГ КУПОНА И ВАЛЮТЫ ИЗ ТЕКСТА
# ============================================================
def extract_bond_info(text):
    info = {}

    # Купон AMD
    amd_match = re.search(r'(\d+\.?\d*)\s*%.*?AMD|AMD.*?(\d+\.?\d*)\s*%', text, re.IGNORECASE)
    if amd_match:
        coupon = float(amd_match.group(1) or amd_match.group(2))
        info["amd_coupon"] = coupon

    # Купон USD
    usd_match = re.search(r'(\d+\.?\d*)\s*%.*?USD|USD.*?(\d+\.?\d*)\s*%', text, re.IGNORECASE)
    if usd_match:
        coupon = float(usd_match.group(1) or usd_match.group(2))
        info["usd_coupon"] = coupon

    # Срок погашения
    mat_match = re.search(r'(\d+)\s*months?|maturity[:\s]+([A-Za-z]+ \d{4}|\d{2}\.\d{2}\.\d{4})', text, re.IGNORECASE)
    if mat_match:
        info["maturity"] = mat_match.group(0)

    # Объём
    vol_match = re.search(r'(AMD|USD)\s*([\d,\.]+\s*(billion|million|bln|mln))', text, re.IGNORECASE)
    if vol_match:
        info["volume"] = vol_match.group(0)

    return info

def is_interesting(info):
    """Проверяет, стоит ли уведомлять об этой облигации"""
    if "amd_coupon" in info and info["amd_coupon"] >= MIN_COUPON_AMD:
        return True
    if "usd_coupon" in info and info["usd_coupon"] >= MIN_COUPON_USD:
        return True
    return False

# ============================================================
# СКРАПИНГ НОВОСТЕЙ
# ============================================================
def fetch_articles(source):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; BondsMonitor/1.0)"}
    articles = []
    try:
        r = requests.get(source["url"], headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        # Ищем все ссылки на статьи
        for a in soup.find_all("a", href=True):
            href = a["href"]
            title = a.get_text(strip=True)

            # Фильтруем по ключевым словам
            if not any(kw.lower() in title.lower() for kw in BOND_KEYWORDS):
                continue
            if len(title) < 15:
                continue

            # Формируем полный URL
            if href.startswith("http"):
                full_url = href
            else:
                full_url = source["base_url"] + href

            articles.append({
                "title": title,
                "url": full_url,
                "source": source["name"]
            })

    except Exception as e:
        print(f"Error fetching {source['name']}: {e}")

    return articles

def fetch_article_text(url):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; BondsMonitor/1.0)"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        # Убираем скрипты и стили
        for tag in soup(["script", "style"]):
            tag.decompose()
        return soup.get_text(" ", strip=True)[:3000]
    except:
        return ""

# ============================================================
# ФОРМАТИРОВАНИЕ УВЕДОМЛЕНИЯ
# ============================================================
def format_message(article, info):
    lines = ["🇦🇲 <b>Новое размещение облигаций!</b>", ""]
    lines.append(f"📰 <b>{article['title']}</b>")
    lines.append(f"🔗 {article['url']}")
    lines.append(f"📡 Источник: {article['source']}")
    lines.append("")

    if "amd_coupon" in info:
        flag = "🟢" if info["amd_coupon"] >= MIN_COUPON_AMD else "🟡"
        lines.append(f"{flag} AMD купон: <b>{info['amd_coupon']}%</b>")
    if "usd_coupon" in info:
        flag = "🟢" if info["usd_coupon"] >= MIN_COUPON_USD else "🟡"
        lines.append(f"{flag} USD купон: <b>{info['usd_coupon']}%</b>")
    if "maturity" in info:
        lines.append(f"📅 Срок: {info['maturity']}")
    if "volume" in info:
        lines.append(f"💰 Объём: {info['volume']}")

    lines.append("")
    lines.append(f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    return "\n".join(lines)

# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================
def run_monitor():
    print(f"[{datetime.now().strftime('%d.%m.%Y %H:%M')}] Запуск мониторинга...")
    seen = load_seen()
    new_count = 0

    for source in SOURCES:
        print(f"  Проверяю {source['name']}...")
        articles = fetch_articles(source)

        for article in articles:
            uid = make_id(article["url"])
            if uid in seen:
                continue

            # Загружаем текст статьи для анализа
            text = article["title"] + " " + fetch_article_text(article["url"])
            info = extract_bond_info(text)

            seen.add(uid)

            if is_interesting(info):
                msg = format_message(article, info)
                if send_telegram(msg):
                    print(f"  ✅ Отправлено: {article['title'][:60]}")
                    new_count += 1
            else:
                print(f"  ℹ️  Не подходит: {article['title'][:60]}")

    save_seen(seen)
    print(f"Готово. Отправлено уведомлений: {new_count}")

    if new_count == 0:
        print("  Новых подходящих размещений не найдено")

# ============================================================
# ЗАПУСК
# ============================================================
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print("Отправляю тестовое сообщение...")
        ok = send_telegram(
            "🤖 <b>Armenia Bonds Monitor запущен!</b>\n\n"
            f"✅ Бот работает\n"
            f"📊 Мин. купон AMD: {MIN_COUPON_AMD}%\n"
            f"💵 Мин. купон USD: {MIN_COUPON_USD}%\n"
            f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        print("✅ Успешно!" if ok else "❌ Ошибка отправки")
    else:
        run_monitor()
