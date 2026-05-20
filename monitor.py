#!/usr/bin/env python3
"""
Armenia Bonds Monitor
1. Мониторит новые размещения облигаций
2. Напоминает о погашении бумаг из портфеля
"""

import requests
import json
import os
import re
import hashlib
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# ============================================================
# НАСТРОЙКИ
# ============================================================
TELEGRAM_TOKEN = "8681090278:AAEAjCYJcx74pzrbU41w4LnHQI_fMmlRxUg"
CHAT_ID = "177924919"
SEEN_FILE = "seen_bonds.json"

MIN_COUPON_AMD = 9.0
MIN_COUPON_USD = 8.0

# ============================================================
# ПОРТФЕЛЬ — бумаги с датами погашения
# ============================================================
PORTFOLIO = [
    {"name": "HELCB1 (ENA Bank AMD)",        "isin": "HELCB1",   "maturity": "2026-12-01", "coupon": "11.4%",  "currency": "AMD"},
    {"name": "HELCB5 (ENA Bank AMD)",         "isin": "HELCB5",   "maturity": "2030-11-01", "coupon": "10.75%", "currency": "AMD"},
    {"name": "ARBBBO (AMIO Bank AMD)",        "isin": "ARBBBO",   "maturity": "2028-03-01", "coupon": "10%",    "currency": "AMD"},
    {"name": "ACBABP (ACBA AMD)",             "isin": "ACBABP",   "maturity": "2031-02-01", "coupon": "10.25%", "currency": "AMD"},
    {"name": "ACBABI (ACBA AMD)",             "isin": "ACBABI",   "maturity": "2029-11-01", "coupon": "10.5%",  "currency": "AMD"},
    {"name": "HEZBBR (ArmEconBank AMD)",      "isin": "HEZBBR",   "maturity": "2029-03-01", "coupon": "10%",    "currency": "AMD"},
    {"name": "ANLBBM1 (ID Bank AMD)",         "isin": "ANLBBM1",  "maturity": "2029-01-01", "coupon": "10%",    "currency": "AMD"},
    {"name": "AMTLB3 (Telecom Armenia AMD)",  "isin": "AMTLB3",   "maturity": "2029-12-01", "coupon": "11.5%",  "currency": "AMD"},
    {"name": "DLNTB1 (Dalan Tech AMD)",       "isin": "DLNTB1",   "maturity": "2028-11-01", "coupon": "13.5%",  "currency": "AMD"},
    {"name": "HELCB3 (ENA Bank USD)",         "isin": "HELCB3",   "maturity": "2029-08-01", "coupon": "7.25%",  "currency": "USD"},
    {"name": "UNIBBS (Unibank USD)",          "isin": "UNIBBS",   "maturity": "2031-11-01", "coupon": "6.25%",  "currency": "USD"},
    {"name": "AMTLB1 (Telecom Armenia USD)",  "isin": "AMTLB1",   "maturity": "2029-12-01", "coupon": "6.75%",  "currency": "USD"},
    {"name": "AMINTMB23ER3 (Intelligent Mgmt)", "isin": "AMINTMB23ER3", "maturity": "2029-05-18", "coupon": "6.5%", "currency": "AMD"},
    {"name": "TMHDB4 (Team Holding USD)",     "isin": "TMHDB4",   "maturity": "2030-05-20", "coupon": "8.65%",  "currency": "USD"},
]

SOURCES = [
    {"name": "ArmBanks", "url": "https://armbanks.am/en/category/capital_market/", "base_url": "https://armbanks.am"},
    {"name": "Banks.am",  "url": "https://banks.am/en/news/capital_market/",       "base_url": "https://banks.am"},
    {"name": "ARKA",      "url": "https://arka.am/en/news/business/",               "base_url": "https://arka.am"},
]

BOND_KEYWORDS = ["bond", "bonds", "placement", "coupon", "maturity", "AMD bond", "USD bond", "issuance", "tranche"]

# ============================================================
# TELEGRAM
# ============================================================
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

# ============================================================
# ПОГАШЕНИЯ ИЗ ПОРТФЕЛЯ
# ============================================================
def check_maturities():
    today = datetime.now().date()
    alerts = []
    
    for bond in PORTFOLIO:
        maturity = datetime.strptime(bond["maturity"], "%Y-%m-%d").date()
        days_left = (maturity - today).days
        
        if days_left < 0:
            continue
        
        # Уведомления за 30, 14, 7, 3, 1 день
        if days_left in [30, 14, 7, 3, 1]:
            alerts.append((bond, days_left, maturity))
    
    for bond, days_left, maturity in alerts:
        if days_left == 1:
            urgency = "🚨 ЗАВТРА ПОГАШЕНИЕ!"
        elif days_left <= 3:
            urgency = f"⚠️ Через {days_left} дня погашение!"
        elif days_left <= 7:
            urgency = f"📅 Через неделю погашение"
        elif days_left <= 14:
            urgency = f"📅 Через 2 недели погашение"
        else:
            urgency = f"📅 Через месяц погашение"
        
        msg = (
            f"{urgency}

"
            f"📄 <b>{bond['name']}</b>
"
            f"💰 Купон: {bond['coupon']} {bond['currency']}
"
            f"📆 Дата погашения: {maturity.strftime('%d.%m.%Y')}
"
            f"⏳ Осталось дней: {days_left}

"
            f"💡 Подумайте о реинвестировании!"
        )
        if send_telegram(msg):
            print(f"✅ Напоминание отправлено: {bond['name']} — через {days_left} дней")

# ============================================================
# МОНИТОРИНГ НОВЫХ ВЫПУСКОВ
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

def extract_bond_info(text):
    info = {}
    amd = re.search(r'(\d+\.?\d*)\s*%.*?AMD|AMD.*?(\d+\.?\d*)\s*%', text, re.IGNORECASE)
    if amd:
        info["amd_coupon"] = float(amd.group(1) or amd.group(2))
    usd = re.search(r'(\d+\.?\d*)\s*%.*?USD|USD.*?(\d+\.?\d*)\s*%', text, re.IGNORECASE)
    if usd:
        info["usd_coupon"] = float(usd.group(1) or usd.group(2))
    mat = re.search(r'(\d+)\s*months?|maturity[:\s]+([A-Za-z]+ \d{4}|\d{2}\.\d{2}\.\d{4})', text, re.IGNORECASE)
    if mat:
        info["maturity"] = mat.group(0)
    vol = re.search(r'(AMD|USD)\s*([\d,\.]+\s*(billion|million|bln|mln))', text, re.IGNORECASE)
    if vol:
        info["volume"] = vol.group(0)
    return info

def is_interesting(info):
    if "amd_coupon" in info and info["amd_coupon"] >= MIN_COUPON_AMD:
        return True
    if "usd_coupon" in info and info["usd_coupon"] >= MIN_COUPON_USD:
        return True
    return False

def fetch_articles(source):
    headers = {"User-Agent": "Mozilla/5.0"}
    articles = []
    try:
        r = requests.get(source["url"], headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            title = a.get_text(strip=True)
            if not any(kw.lower() in title.lower() for kw in BOND_KEYWORDS):
                continue
            if len(title) < 15:
                continue
            full_url = href if href.startswith("http") else source["base_url"] + href
            articles.append({"title": title, "url": full_url, "source": source["name"]})
    except Exception as e:
        print(f"Error fetching {source['name']}: {e}")
    return articles

def fetch_article_text(url):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        return soup.get_text(" ", strip=True)[:3000]
    except:
        return ""

def format_message(article, info):
    lines = ["🇦🇲 <b>Новое размещение облигаций!</b>", ""]
    lines.append(f"📰 <b>{article['title']}</b>")
    lines.append(f"🔗 {article['url']}")
    lines.append(f"📡 {article['source']}")
    lines.append("")
    if "amd_coupon" in info:
        lines.append(f"💚 AMD купон: <b>{info['amd_coupon']}%</b>")
    if "usd_coupon" in info:
        lines.append(f"💵 USD купон: <b>{info['usd_coupon']}%</b>")
    if "maturity" in info:
        lines.append(f"📅 Срок: {info['maturity']}")
    if "volume" in info:
        lines.append(f"💰 Объём: {info['volume']}")
    lines.append(f"\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    return "\n".join(lines)

def run_new_bonds_monitor():
    seen = load_seen()
    new_count = 0
    for source in SOURCES:
        articles = fetch_articles(source)
        for article in articles:
            uid = make_id(article["url"])
            if uid in seen:
                continue
            text = article["title"] + " " + fetch_article_text(article["url"])
            info = extract_bond_info(text)
            seen.add(uid)
            if is_interesting(info):
                if send_telegram(format_message(article, info)):
                    new_count += 1
    save_seen(seen)
    print(f"Новых размещений отправлено: {new_count}")

# ============================================================
# ЗАПУСК
# ============================================================
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        send_telegram(
            "🤖 <b>Armenia Bonds Monitor — тест</b>\n\n"
            "✅ Новые выпуски: мониторинг активен\n"
            f"📊 Мин. купон AMD: {MIN_COUPON_AMD}%\n"
            f"💵 Мин. купон USD: {MIN_COUPON_USD}%\n"
            f"📋 Бумаг в портфеле: {len(PORTFOLIO)}\n"
            "🔔 Напоминания о погашении: за 30/14/7/3/1 день"
        )
    else:
        print("=== Проверка погашений портфеля ===")
        check_maturities()
        print("=== Мониторинг новых выпусков ===")
        run_new_bonds_monitor()
