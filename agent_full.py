import asyncio
import aiohttp
import sqlite3
import re
from datetime import datetime, timedelta
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, ConversationHandler

# --- Токен и чат ---
TELEGRAM_TOKEN = "8736932989:AAHXkaXco6fs3_EdR4VXP3YcpfDA05mrdsw"
CHAT_ID = "853299211"

CURRENCY_SYMBOL = {1: "$", 5: "₽", 18: "₴", 37: "₸", 23: "¥"}
CURRENCY_NAMES  = {"usd": 1, "rub": 5, "uah": 18, "kzt": 37, "cny": 23}

WAITING_INVENTORY = 1

# --- БД ---
def init_db():
    conn = sqlite3.connect("prices.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            item TEXT, price REAL, volume INTEGER,
            currency INTEGER, timestamp INTEGER
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_prices
        ON prices(item, currency, timestamp)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            name TEXT PRIMARY KEY,
            appid INTEGER,
            added_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id TEXT PRIMARY KEY, steam_url TEXT,
            steam_id TEXT, added_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_items (
            chat_id TEXT, item_name TEXT, appid INTEGER, added_at INTEGER,
            PRIMARY KEY (chat_id, item_name)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_config (
            key TEXT PRIMARY KEY, value TEXT
        )
    """)
    conn.commit()
    return conn

def load_config_from_db(conn):
    """Читает конфиг из БД — обновляется панелью без перезапуска"""
    def gcfg(key, default):
        row = conn.execute(
            "SELECT value FROM bot_config WHERE key=?", (key,)
        ).fetchone()
        return row[0] if row else default
    return {
        "CHECK_INTERVAL":      int(gcfg("CHECK_INTERVAL", 300)),
        "SPIKE_THRESHOLD_1H":  float(gcfg("SPIKE_THRESHOLD_1H", 15)),
        "SPIKE_THRESHOLD_24H": float(gcfg("SPIKE_THRESHOLD_24H", 30)),
        "DROP_THRESHOLD_1H":   float(gcfg("DROP_THRESHOLD_1H", -10)),
        "DROP_THRESHOLD_24H":  float(gcfg("DROP_THRESHOLD_24H", -20)),
        "MIN_VOLUME":          int(gcfg("MIN_VOLUME", 5)),
        "CURRENCY":            int(gcfg("CURRENCY", 1)),
    }

def get_watchlist(conn):
    """Читает watchlist из БД — управляется через панель"""
    rows = conn.execute("SELECT name, appid FROM watchlist").fetchall()
    return [{"name": r[0], "appid": r[1]} for r in rows]

def save_price(conn, item, price, volume, currency):
    conn.execute(
        "INSERT INTO prices VALUES (?, ?, ?, ?, ?)",
        (item, price, volume, currency, int(datetime.now().timestamp()))
    )
    conn.commit()

def get_price_ago(conn, item, seconds_ago, currency):
    cutoff = int(datetime.now().timestamp()) - seconds_ago
    row = conn.execute(
        """SELECT price FROM prices
           WHERE item=? AND currency=? AND timestamp <= ?
           ORDER BY timestamp DESC LIMIT 1""",
        (item, currency, cutoff)
    ).fetchone()
    return row[0] if row else None

def get_avg_price(conn, item, days_ago, currency):
    cutoff = int((datetime.now() - timedelta(days=days_ago)).timestamp())
    row = conn.execute(
        """SELECT AVG(price) FROM prices
           WHERE item=? AND currency=? AND timestamp >= ?""",
        (item, currency, cutoff)
    ).fetchone()
    return round(row[0], 2) if row and row[0] else None

def get_records_count(conn, item):
    row = conn.execute(
        "SELECT COUNT(*) FROM prices WHERE item=?", (item,)
    ).fetchone()
    return row[0] if row else 0

def purge_old_data(conn):
    cutoff = int((datetime.now() - timedelta(days=35)).timestamp())
    conn.execute("DELETE FROM prices WHERE timestamp < ?", (cutoff,))
    conn.commit()

def save_user(conn, chat_id, steam_url, steam_id):
    conn.execute(
        "INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?)",
        (str(chat_id), steam_url, steam_id, int(datetime.now().timestamp()))
    )
    conn.commit()

def save_user_items(conn, chat_id, items):
    conn.execute("DELETE FROM user_items WHERE chat_id=?", (str(chat_id),))
    for item in items:
        conn.execute(
            "INSERT OR IGNORE INTO user_items VALUES (?, ?, ?, ?)",
            (str(chat_id), item["name"], item["appid"], int(datetime.now().timestamp()))
        )
    conn.commit()

def get_user_items(conn, chat_id):
    rows = conn.execute(
        "SELECT item_name, appid FROM user_items WHERE chat_id=?",
        (str(chat_id),)
    ).fetchall()
    return [{"name": r[0], "appid": r[1]} for r in rows]

def get_all_users(conn):
    rows = conn.execute("SELECT chat_id FROM users").fetchall()
    return [r[0] for r in rows]

def get_user(conn, chat_id):
    return conn.execute(
        "SELECT steam_url, steam_id FROM users WHERE chat_id=?",
        (str(chat_id),)
    ).fetchone()

# --- Steam API ---
def extract_steam_id(url):
    url = url.strip().rstrip("/")
    m = re.search(r'/profiles/(\d{17})', url)
    if m:
        return m.group(1), "id64"
    m = re.search(r'/id/([^/]+)', url)
    if m:
        return m.group(1), "vanity"
    return None, None

async def resolve_vanity(session, vanity):
    url = f"https://steamcommunity.com/id/{vanity}/?xml=1"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            text = await resp.text()
            m = re.search(r'<steamID64>(\d+)</steamID64>', text)
            if m:
                return m.group(1)
    except Exception as e:
        print(f"Ошибка resolve vanity: {e}")
    return None

async def fetch_inventory(session, steam_id64):
    url = f"https://steamcommunity.com/inventory/{steam_id64}/730/2"
    params = {"l": "english", "count": 500}
    try:
        async with session.get(
            url, params=params, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status == 403:
                return None, "Инвентарь закрыт. Открой: Steam → Профиль → Конфиденциальность → Инвентарь: Публичный"
            if resp.status == 429:
                return None, "Steam ограничил запросы, попробуй через минуту"
            data = await resp.json()
            if not data.get("success"):
                return None, "Steam вернул ошибку, попробуй позже"

            descriptions = {
                f"{d['classid']}_{d['instanceid']}": d
                for d in data.get("descriptions", [])
            }

            items = []
            seen = set()
            for asset in data.get("assets", []):
                key = f"{asset['classid']}_{asset['instanceid']}"
                desc = descriptions.get(key, {})
                name = desc.get("market_hash_name")
                if not name or name in seen:
                    continue
                if desc.get("marketable", 0) == 1:
                    items.append({"name": name, "appid": 730})
                    seen.add(name)

            return items, None
    except Exception as e:
        return None, f"Ошибка: {e}"

async def fetch_price(session, item_name, appid, currency):
    url = "https://steamcommunity.com/market/priceoverview/"
    params = {
        "appid": appid,
        "currency": currency,
        "market_hash_name": item_name
    }
    try:
        async with session.get(
            url, params=params, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            data = await resp.json()
            if data.get("success"):
                price_str = data.get("lowest_price", "0")
                price_str = re.sub(r'[^\d,.]', '', price_str).strip()
                if ',' in price_str and '.' in price_str:
                    price_str = price_str.replace(',', '')
                elif ',' in price_str:
                    price_str = price_str.replace(',', '.')
                volume_str = re.sub(r'[^\d]', '', data.get("volume", "0"))
                return float(price_str or 0), int(volume_str or 0)
    except Exception as e:
        print(f"Ошибка цены {item_name}: {e}")
    return None, None

# --- Форматирование ---
def fmt(price, currency):
    sym = CURRENCY_SYMBOL.get(currency, "$")
    if currency in (5, 18, 37):
        return f"{price:,.0f} {sym}"
    return f"{sym}{price:,.2f}"

def pct_str(current, old):
    if not old or old == 0:
        return None, "нет данных"
    pct = ((current - old) / old) * 100
    icon = "📈" if pct > 0 else "📉"
    return pct, f"{icon} {pct:+.1f}%"

# --- Telegram сообщения ---
async def send_startup(bot, watchlist):
    items_text = "\n".join([f"  • {i['name']}" for i in watchlist])
    text = (
        "✅ <b>Бот запущен!</b>\n\n"
        f"Скинов в watchlist: <b>{len(watchlist)}</b>\n{items_text}\n\n"
        "Команды:\n"
        "/inventory — добавить инвентарь Steam\n"
        "/myitems — мои скины\n"
        "/status — цены по моим скинам\n"
        "/history — сравнение с историей\n"
        "/watchlist — общий список\n"
        "/dbinfo — состояние БД\n"
        "/help — помощь"
    )
    await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML")

async def send_alert(bot, chat_id, item_name, current, old, pct, period_label, is_drop, currency):
    icon = "📉" if is_drop else "🚀"
    word = "Просадка" if is_drop else "Скачок"
    encoded = item_name.replace(" ", "%20").replace("|", "%7C")
    text = (
        f"{icon} <b>{word}!</b>\n\n"
        f"<b>{item_name}</b>\n"
        f"За: <b>{period_label}</b>\n"
        f"Было: <b>{fmt(old, currency)}</b>\n"
        f"Стало: <b>{fmt(current, currency)}</b>\n"
        f"Изменение: <b>{pct:+.1f}%</b>\n\n"
        f'<a href="https://steamcommunity.com/market/listings/730/{encoded}">Открыть на маркете</a>'
    )
    await bot.send_message(chat_id=str(chat_id), text=text, parse_mode="HTML")

# --- ConversationHandler для инвентаря ---
async def cmd_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎒 <b>Добавление инвентаря</b>\n\n"
        "Отправь ссылку на профиль Steam:\n\n"
        "<code>https://steamcommunity.com/id/никнейм</code>\n"
        "<code>https://steamcommunity.com/profiles/76561198xxxxxxxxx</code>\n\n"
        "❗ Инвентарь должен быть публичным:\n"
        "Steam → Профиль → Конфиденциальность → Инвентарь игр: Публичный\n\n"
        "Отмена: /cancel",
        parse_mode="HTML"
    )
    return WAITING_INVENTORY

async def receive_inventory_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    chat_id = update.effective_chat.id

    steam_id, id_type = extract_steam_id(url)
    if not steam_id:
        await update.message.reply_text(
            "❌ Не могу распознать ссылку. Попробуй ещё раз или /cancel"
        )
        return WAITING_INVENTORY

    await update.message.reply_text("🔄 Загружаю инвентарь...")

    async with aiohttp.ClientSession() as session:
        steam_id64 = steam_id
        if id_type == "vanity":
            steam_id64 = await resolve_vanity(session, steam_id)
            if not steam_id64:
                await update.message.reply_text(
                    "❌ Не удалось найти аккаунт. Попробуй ссылку с /profiles/ID"
                )
                return WAITING_INVENTORY

        items, error = await fetch_inventory(session, steam_id64)

    if error:
        await update.message.reply_text(f"❌ {error}")
        return WAITING_INVENTORY

    if not items:
        await update.message.reply_text(
            "😕 В инвентаре не найдено маркетабельных CS2 предметов"
        )
        return ConversationHandler.END

    conn = init_db()
    save_user(conn, chat_id, url, steam_id64)
    save_user_items(conn, chat_id, items)
    conn.close()

    preview = "\n".join([f"  • {i['name']}" for i in items[:10]])
    more = f"\n  ... и ещё {len(items) - 10}" if len(items) > 10 else ""

    await update.message.reply_text(
        f"✅ <b>Инвентарь добавлен!</b>\n\n"
        f"Найдено скинов: <b>{len(items)}</b>\n\n"
        f"{preview}{more}\n\n"
        f"Бот будет отслеживать цены и присылать алерты.\n"
        f"/myitems — посмотреть список",
        parse_mode="HTML"
    )
    return ConversationHandler.END

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END

# --- Команды ---
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 <b>Команды:</b>\n\n"
        "/inventory — добавить инвентарь Steam\n"
        "/myitems — мои скины\n"
        "/status — текущие цены\n"
        "/history — сравнение с историей\n"
        "/watchlist — общий список\n"
        "/dbinfo — состояние БД\n"
        "/help — это сообщение",
        parse_mode="HTML"
    )

async def cmd_myitems(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conn = init_db()
    items = get_user_items(conn, chat_id)
    user  = get_user(conn, chat_id)
    conn.close()

    if not items:
        await update.message.reply_text(
            "У тебя нет добавленных скинов.\n/inventory — добавить инвентарь"
        )
        return

    preview = "\n".join([f"  • {i['name']}" for i in items[:20]])
    more = f"\n  ... и ещё {len(items) - 20}" if len(items) > 20 else ""
    await update.message.reply_text(
        f"🎒 <b>Твои скины ({len(items)}):</b>\n\n{preview}{more}\n\n"
        f"Профиль: {user[0] if user else '—'}",
        parse_mode="HTML"
    )

async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = init_db()
    watchlist = get_watchlist(conn)
    conn.close()
    items_text = "\n".join([f"  • {i['name']}" for i in watchlist])
    await update.message.reply_text(
        f"👀 <b>Общий watchlist ({len(watchlist)}):</b>\n\n{items_text}\n\n"
        f"Управление через панель: http://localhost:5000",
        parse_mode="HTML"
    )

async def cmd_dbinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conn = init_db()
    items = get_user_items(conn, chat_id)
    if not items:
        items = get_watchlist(conn)
    lines = ["🗄 <b>База данных:</b>\n"]
    for item in items[:8]:
        count = get_records_count(conn, item["name"])
        lines.append(f"<b>{item['name'][:40]}</b>\n  {count} записей")
    conn.close()
    await update.message.reply_text("\n\n".join(lines), parse_mode="HTML")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conn = init_db()
    cfg = load_config_from_db(conn)
    currency = cfg["CURRENCY"]
    items = get_user_items(conn, chat_id) or get_watchlist(conn)

    await update.message.reply_text(f"🔄 Проверяю {len(items)} скинов...")
    lines = []
    async with aiohttp.ClientSession() as session:
        for item in items[:15]:
            price, volume = await fetch_price(session, item["name"], item["appid"], currency)
            if price:
                price_1h = get_price_ago(conn, item["name"], 3600, currency)
                if price_1h:
                    pct, pct_text = pct_str(price, price_1h)
                    trend = f"{pct_text} за 1ч"
                else:
                    trend = "⏳ накапливаю историю"
                lines.append(
                    f"<b>{item['name']}</b>\n"
                    f"  {fmt(price, currency)}  |  объём: {volume}\n"
                    f"  {trend}"
                )
            else:
                lines.append(f"<b>{item['name']}</b>\n  ❌ нет данных")
            await asyncio.sleep(4)
    conn.close()
    if lines:
        await update.message.reply_text("\n\n".join(lines), parse_mode="HTML")

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conn = init_db()
    cfg = load_config_from_db(conn)
    currency = cfg["CURRENCY"]
    items = get_user_items(conn, chat_id) or get_watchlist(conn)

    await update.message.reply_text(f"📊 Загружаю историю для {len(items)} скинов...")
    lines = []
    async with aiohttp.ClientSession() as session:
        for item in items[:15]:
            price, _ = await fetch_price(session, item["name"], item["appid"], currency)
            if not price:
                lines.append(f"<b>{item['name']}</b>\n  ❌ нет данных")
                await asyncio.sleep(4)
                continue

            p1d  = get_price_ago(conn, item["name"], 86400, currency)
            p7d  = get_avg_price(conn, item["name"], 7, currency)
            p30d = get_avg_price(conn, item["name"], 30, currency)

            def line(old, label):
                if not old:
                    return f"  {label}: ⏳ данных ещё нет"
                _, ps = pct_str(price, old)
                return f"  {label}: {ps} (было {fmt(old, currency)})"

            lines.append(
                f"<b>{item['name']}</b>\n"
                f"  Сейчас: <b>{fmt(price, currency)}</b>\n"
                f"{line(p1d,  '1 день')}\n"
                f"{line(p7d,  '7 дней avg')}\n"
                f"{line(p30d, '30 дней avg')}"
            )
            await asyncio.sleep(4)
    conn.close()
    if lines:
        await update.message.reply_text("\n\n".join(lines), parse_mode="HTML")

# --- Мониторинг ---
async def monitor_loop(bot):
    conn = init_db()
    last_purge = datetime.now().date()

    async with aiohttp.ClientSession() as session:
        while True:
            # Читаем актуальный конфиг и watchlist из БД каждый цикл
            cfg = load_config_from_db(conn)
            CHECK_INTERVAL      = cfg["CHECK_INTERVAL"]
            SPIKE_THRESHOLD_1H  = cfg["SPIKE_THRESHOLD_1H"]
            SPIKE_THRESHOLD_24H = cfg["SPIKE_THRESHOLD_24H"]
            DROP_THRESHOLD_1H   = cfg["DROP_THRESHOLD_1H"]
            DROP_THRESHOLD_24H  = cfg["DROP_THRESHOLD_24H"]
            MIN_VOLUME          = cfg["MIN_VOLUME"]
            CURRENCY            = cfg["CURRENCY"]
            WATCHLIST           = get_watchlist(conn)

            print(f"[{datetime.now().strftime('%H:%M:%S')}] Проверяю цены... "
                  f"(валюта: {CURRENCY}, скинов: {len(WATCHLIST)})")

            all_users = get_all_users(conn)
            user_items_map = {}
            all_items = {i["name"]: i for i in WATCHLIST}

            for chat_id in all_users:
                items = get_user_items(conn, chat_id)
                user_items_map[chat_id] = items
                for i in items:
                    all_items[i["name"]] = i

            for name, item in all_items.items():
                price, volume = await fetch_price(session, name, item["appid"], CURRENCY)
                if not price or volume < MIN_VOLUME:
                    await asyncio.sleep(4)
                    continue

                price_1h  = get_price_ago(conn, name, 3600, CURRENCY)
                price_24h = get_price_ago(conn, name, 86400, CURRENCY)
                save_price(conn, name, price, volume, CURRENCY)

                for old, label, spike_thr, drop_thr in [
                    (price_1h,  "1 час",   SPIKE_THRESHOLD_1H,  DROP_THRESHOLD_1H),
                    (price_24h, "24 часа", SPIKE_THRESHOLD_24H, DROP_THRESHOLD_24H),
                ]:
                    if old and old > 0:
                        pct = ((price - old) / old) * 100
                        if pct >= spike_thr or pct <= drop_thr:
                            is_drop = pct <= drop_thr
                            if name in {i["name"] for i in WATCHLIST}:
                                await send_alert(bot, CHAT_ID, name, price, old, pct, label, is_drop, CURRENCY)
                            for uid, u_items in user_items_map.items():
                                if any(i["name"] == name for i in u_items):
                                    if str(uid) != str(CHAT_ID):
                                        await send_alert(bot, uid, name, price, old, pct, label, is_drop, CURRENCY)

                await asyncio.sleep(4)

            today = datetime.now().date()
            if today > last_purge:
                purge_old_data(conn)
                last_purge = today
                print("БД очищена от данных старше 35 дней")

            print(f"Следующая проверка через {CHECK_INTERVAL // 60} мин.")
            await asyncio.sleep(CHECK_INTERVAL)

# --- Запуск ---
async def main():
    conn = init_db()
    watchlist = get_watchlist(conn)
    conn.close()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    inv_handler = ConversationHandler(
        entry_points=[CommandHandler("inventory", cmd_inventory)],
        states={
            WAITING_INVENTORY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_inventory_url)
            ]
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    app.add_handler(inv_handler)
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("myitems",   cmd_myitems))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("history",   cmd_history))
    app.add_handler(CommandHandler("dbinfo",    cmd_dbinfo))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await send_startup(app.bot, watchlist)
    await monitor_loop(app.bot)

if __name__ == "__main__":
    asyncio.run(main())
