#!/usr/bin/env python3
"""
Armenia Bonds Monitor
1. Новые размещения облигаций
2. Напоминания о погашении бумаг портфеля
3. Новости: эмитенты портфеля, макро Армении, геополитика, купонные выплаты
"""

import requests
import json
import os
import re
import hashlib
import time
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from urllib.parse import quote
from email.utils import parsedate_to_datetime

# ============================================================
# НАСТРОЙКИ
# ============================================================
TELEGRAM_TOKEN = "8681090278:AAEAjCYJcx74pzrbU41w4LnHQI_fMmlRxUg"
CHAT_ID = "177924919"
SEEN_FILE = "seen_bonds.json"
SEEN_NEWS_FILE = "seen_news.json"

MIN_COUPON_AMD = 9.0
MIN_COUPON_USD = 8.0

# Новости за последние N часов (с запасом — запуски 9:00 и 18:00)
NEWS_LOOKBACK_HOURS = 12

# ============================================================
# ПОРТФЕЛЬ — бумаги с датами погашения и купонными датами
# ============================================================
PORTFOLIO = [
    {"name": "HELCB5 (ENA AMD)",           "isin": "HELCB5",       "maturity": "2030-11-01", "coupon": "10.75%", "currency": "AMD", "coupon_freq_months": 3},
    {"name": "ACBABP (ACBA AMD)",          "isin": "ACBABP",       "maturity": "2031-02-01", "coupon": "10.25%", "currency": "AMD", "coupon_freq_months": 6},
    {"name": "ACBABI (ACBA AMD)",          "isin": "ACBABI",       "maturity": "2029-11-01", "coupon": "10.5%",  "currency": "AMD", "coupon_freq_months": 6},
    {"name": "AMTLB3 (Telecom Armenia AMD)","isin": "AMTLB3",      "maturity": "2029-12-01", "coupon": "11.5%",  "currency": "AMD", "coupon_freq_months": 6},
    {"name": "DLNTB1 (Dalan Tech AMD)",    "isin": "DLNTB1",       "maturity": "2028-11-01", "coupon": "13.5%",  "currency": "AMD", "coupon_freq_months": 6},
    {"name": "HELCB3 (ENA USD)",           "isin": "HELCB3",       "maturity": "2029-08-01", "coupon": "7.25%",  "currency": "USD", "coupon_freq_months": 3},
    {"name": "UNIBBS (Unibank USD)",       "isin": "UNIBBS",       "maturity": "2031-11-01", "coupon": "6.25%",  "currency": "USD", "coupon_freq_months": 6},
    {"name": "AMTLB1 (Telecom Armenia USD)","isin": "AMTLB1",      "maturity": "2029-12-01", "coupon": "6.75%",  "currency": "USD", "coupon_freq_months": 6},
    {"name": "AMINTMB23ER3 (Intelligent Mgmt AMD)", "isin": "AMINTMB23ER3", "maturity": "2029-05-18", "coupon": "11.9%", "currency": "AMD", "coupon_freq_months": 6},
    {"name": "TMHDB4 (Team Holding USD)",  "isin": "TMHDB4",       "maturity": "2030-05-20", "coupon": "8.65%",  "currency": "USD", "coupon_freq_months": 6},
]

# ============================================================
# ИСТОЧНИКИ ДЛЯ НОВЫХ РАЗМЕЩЕНИЙ
# ============================================================
SOURCES = [
    {"name": "ArmBanks", "url": "https://armbanks.am/en/category/capital_market/", "base_url": "https://armbanks.am"},
    {"name": "Banks.am",  "url": "https://banks.am/en/news/capital_market/",       "base_url": "https://banks.am"},
    {"name": "ARKA",      "url": "https://arka.am/en/news/business/",               "base_url": "https://arka.am"},
]

BOND_KEYWORDS = ["bond", "bonds", "placement", "coupon", "maturity", "AMD bond", "USD bond", "issuance", "tranche"]

# ============================================================
# НОВОСТНЫЕ ЗАПРОСЫ (Google News RSS)
# Каждый запрос — отдельная категория. Все они идут в одно сообщение.
# ============================================================
NEWS_QUERIES = {
    "Эмитенты портфеля": [
        # ENA — самая горячая история
        '"Electric Networks of Armenia" OR ENA Armenia',
        '"Электрические сети Армении"',
        # Team Holding / Telecom Armenia
        '"Team Holding" Armenia bonds',
        '"Telecom Armenia" OR "Team Telecom Armenia"',
        # Прочие эмитенты
        '"Dalan Technopark" OR "Dalan Technologies"',
        '"Intelligent Management" Armenia bonds',
        # Банки портфеля
        '"ACBA Bank" Armenia',
        '"Unibank" Armenia',
        '"Ameriabank"',
        '"Freedom Broker Armenia" OR "Freedom Finance Armenia"',
    ],
    "Макро Армении": [
        'Armenia "Central Bank" rate decision',
        'Armenia Moody\'s OR Fitch OR "S&P" rating',
        'Armenia GDP OR inflation 2026',
        'Armenia budget deficit 2026',
        'Armenia bond market',
    ],
    "Геополитика и арбитражи": [
        '"Samvel Karapetyan" Armenia',
        'Armenia Stockholm arbitration ENA',
        'Armenia sanctions OR sanctioned',
        'Armenia Azerbaijan peace',
        'Armenia Russia EAEU',
    ],
}

# ============================================================
# TELEGRAM
# ============================================================
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # Telegram лимит 4096 символов — режем если длиннее
    if len(message) > 4000:
        message = message[:3950] + "\n\n…(обрезано)"
    try:
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

def send_long_message(header, items):
    """Отправляет длинное сообщение, разбивая на части если нужно."""
    if not items:
        return 0
    chunks = []
    current = [header, ""]
    current_len = len(header) + 2
    for item in items:
        if current_len + len(item) + 2 > 3800:
            chunks.append("\n".join(current))
            current = [f"{header} (продолжение)", ""]
            current_len = len(header) + 15
        current.append(item)
        current_len += len(item) + 2
    if len(current) > 2:
        chunks.append("\n".join(current))
    sent = 0
    for chunk in chunks:
        if send_telegram(chunk):
            sent += 1
        time.sleep(0.5)
    return sent

# ============================================================
# ПОГАШЕНИЯ ИЗ ПОРТФЕЛЯ
# ============================================================
def check_maturities():
    today = datetime.now().date()
    for bond in PORTFOLIO:
        maturity = datetime.strptime(bond["maturity"], "%Y-%m-%d").date()
        days_left = (maturity - today).days
        if days_left < 0:
            continue
        if days_left in [30, 14, 7, 3, 1]:
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
                f"{urgency}\n\n"
                f"📄 <b>{bond['name']}</b>\n"
                f"💰 Купон: {bond['coupon']} {bond['currency']}\n"
                f"📆 Дата погашения: {maturity.strftime('%d.%m.%Y')}\n"
                f"⏳ Осталось дней: {days_left}\n\n"
                f"💡 Подумай о реинвестировании!"
            )
            if send_telegram(msg):
                print(f"✅ Напоминание: {bond['name']} — {days_left} дней")

# ============================================================
# КУПОННЫЕ ВЫПЛАТЫ
# Считаем следующую купонную дату от maturity, идя назад.
# Напоминаем за 3 дня и в день выплаты, проверяем через 5 дней.
# ============================================================
def get_coupon_dates(bond):
    """Возвращает все купонные даты от сегодня до погашения."""
    maturity = datetime.strptime(bond["maturity"], "%Y-%m-%d").date()
    freq = bond.get("coupon_freq_months", 6)
    today = datetime.now().date()
    dates = []
    d = maturity
    while d > today - timedelta(days=30):
        if d >= today - timedelta(days=30):
            dates.append(d)
        # вычитаем freq месяцев
        new_month = d.month - freq
        new_year = d.year
        while new_month <= 0:
            new_month += 12
            new_year -= 1
        try:
            d = d.replace(year=new_year, month=new_month)
        except ValueError:
            break
        if d < today - timedelta(days=60):
            break
    return sorted(dates)

def check_coupons():
    today = datetime.now().date()
    alerts = []
    for bond in PORTFOLIO:
        for coupon_date in get_coupon_dates(bond):
            delta = (coupon_date - today).days
            if delta == 3:
                alerts.append(f"💰 <b>{bond['name']}</b> — купон через 3 дня ({coupon_date.strftime('%d.%m.%Y')}, {bond['coupon']} {bond['currency']})")
            elif delta == 0:
                alerts.append(f"✅ <b>{bond['name']}</b> — купон сегодня ({bond['coupon']} {bond['currency']}). Проверь зачисление в Ameriabank/Freedom.")
            elif delta == -5:
                alerts.append(f"❓ <b>{bond['name']}</b> — купон был 5 дней назад ({coupon_date.strftime('%d.%m.%Y')}). Если не зачислили — напиши брокеру.")
    if alerts:
        send_long_message("💵 <b>Купонные выплаты</b>", alerts)

# ============================================================
# МОНИТОРИНГ НОВЫХ ВЫПУСКОВ (как было)
# ============================================================
def load_seen(path=SEEN_FILE):
    if os.path.exists(path):
        with open(path, "r") as f:
            return set(json.load(f))
    return set()

def save_seen(seen, path=SEEN_FILE):
    with open(path, "w") as f:
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

def format_bond_message(article, info):
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
                if send_telegram(format_bond_message(article, info)):
                    new_count += 1
    save_seen(seen)
    print(f"Новых размещений: {new_count}")

# ============================================================
# НОВОСТИ ЧЕРЕЗ GOOGLE NEWS RSS
# Один запрос на тему → собираем все свежие за NEWS_LOOKBACK_HOURS часов
# ============================================================
def fetch_google_news(query):
    """Возвращает список свежих новостей по запросу из Google News RSS."""
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en&gl=AM&ceid=AM:en"
    items = []
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        soup = BeautifulSoup(r.content, "xml")
        cutoff = datetime.now().astimezone() - timedelta(hours=NEWS_LOOKBACK_HOURS)
        for it in soup.find_all("item"):
            title = it.title.text if it.title else ""
            link = it.link.text if it.link else ""
            pub = it.pubDate.text if it.pubDate else ""
            source_tag = it.find("source")
            source = source_tag.text if source_tag else ""
            try:
                pub_dt = parsedate_to_datetime(pub)
                if pub_dt < cutoff:
                    continue
            except Exception:
                continue
            items.append({"title": title, "url": link, "source": source, "pub": pub_dt})
    except Exception as e:
        print(f"Google News error для '{query}': {e}")
    return items

def run_news_monitor():
    seen = load_seen(SEEN_NEWS_FILE)
    grouped = {}
    for category, queries in NEWS_QUERIES.items():
        items = []
        for q in queries:
            for it in fetch_google_news(q):
                uid = make_id(it["url"])
                if uid in seen:
                    continue
                seen.add(uid)
                items.append(it)
            time.sleep(0.3)  # не долбим Google
        # дедуп внутри категории по заголовку
        unique = {}
        for it in items:
            key = it["title"][:80].lower()
            if key not in unique:
                unique[key] = it
        grouped[category] = sorted(unique.values(), key=lambda x: x["pub"], reverse=True)

    save_seen(seen, SEEN_NEWS_FILE)

    # Формируем сообщения по категориям
    emoji = {"Эмитенты портфеля": "🏢", "Макро Армении": "📊", "Геополитика и арбитражи": "⚖️"}
    total = 0
    for category, items in grouped.items():
        if not items:
            continue
        header = f"{emoji.get(category, '📰')} <b>{category}</b> ({len(items)})"
        lines = []
        for it in items:
            t = it["title"]
            # отрезаем " - Source Name" в конце заголовка Google News, оно дублирует source
            t = re.sub(r'\s*-\s*[^-]+$', '', t)
            src = it["source"] or "—"
            lines.append(f"• <a href=\"{it['url']}\">{t}</a> <i>({src})</i>")
        sent = send_long_message(header, lines)
        total += sent
        time.sleep(0.5)
    print(f"Новостных сообщений отправлено: {total}")

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
            "🔔 Напоминания о погашении: за 30/14/7/3/1 день\n"
            "💵 Купоны: за 3 дня, в день выплаты, проверка через 5 дней\n"
            "📰 Новости: эмитенты + макро + геополитика, 2 раза в день"
        )
    elif len(sys.argv) > 1 and sys.argv[1] == "news":
        # Только новости — для отладки
        run_news_monitor()
    else:
        print("=== Погашения портфеля ===")
        check_maturities()
        print("=== Купонные выплаты ===")
        check_coupons()
        print("=== Новые выпуски ===")
        run_new_bonds_monitor()
        print("=== Новости ===")
        run_news_monitor()
