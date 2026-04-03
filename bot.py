import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import asyncio
import aiohttp
import sqlite3
import re
import random
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = "8736932989:AAGYcc9WfAaW1j99t3qUCEYTwwFn31iamic"
DB_PATH        = "prices.db"

CURRENCY_SYMBOL = {1: "$", 5: "₽", 18: "₴", 37: "₸", 23: "¥"}

# Cooldown: не посылаем повторный алерт по одному скину+периоду быстрее 2 часов
_alerted: dict = {}
ALERT_COOLDOWN  = 7200  # секунд


# ─── БД ──────────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            telegram_id TEXT PRIMARY KEY,
            role        TEXT    DEFAULT 'user',
            created_at  INTEGER,
            username    TEXT    DEFAULT '',
            first_name  TEXT    DEFAULT ''
        )
    """)
    for col in ("username TEXT DEFAULT ''", "first_name TEXT DEFAULT ''"):
        try:
            conn.execute(f"ALTER TABLE accounts ADD COLUMN {col}")
        except Exception:
            pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS auth_tokens (
            token       TEXT PRIMARY KEY,
            telegram_id TEXT,
            expires_at  INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_config (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            item      TEXT,
            price     REAL,
            volume    INTEGER,
            currency  INTEGER,
            timestamp INTEGER
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_prices
        ON prices(item, currency, timestamp)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            chat_id     TEXT NOT NULL DEFAULT '',
            name        TEXT NOT NULL,
            appid       INTEGER,
            added_at    INTEGER,
            rarity      TEXT,
            rarity_color TEXT,
            PRIMARY KEY (chat_id, name)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_items (
            chat_id   TEXT,
            item_name TEXT,
            appid     INTEGER,
            added_at  INTEGER,
            notify    INTEGER DEFAULT 1,
            PRIMARY KEY (chat_id, item_name)
        )
    """)
    try:
        conn.execute("ALTER TABLE user_items ADD COLUMN notify INTEGER DEFAULT 1")
    except Exception:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS item_rarity (
            name         TEXT PRIMARY KEY,
            rarity       TEXT,
            rarity_color TEXT,
            item_type    TEXT,
            icon_url     TEXT DEFAULT ''
        )
    """)
    try:
        conn.execute("ALTER TABLE users ADD COLUMN last_synced INTEGER DEFAULT 0")
    except Exception:
        pass
    # Таблица для отслеживания уже уведомлённых trade offer-ов
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notified_offers (
            offer_id    INTEGER PRIMARY KEY,
            notified_at INTEGER
        )
    """)
    # Очередь уведомлений от сайта (принятые трейды и др.)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_tg_notifications (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id    TEXT    NOT NULL,
            message    TEXT    NOT NULL,
            sent       INTEGER DEFAULT 0,
            created_at INTEGER
        )
    """)

    conn.commit()
    conn.close()


def register_user(telegram_id: str, username: str = "", first_name: str = ""):
    """Регистрирует пользователя в таблице accounts (если ещё нет), обновляет имя."""
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO accounts (telegram_id, role, created_at, username, first_name) "
        "VALUES (?,?,?,?,?)",
        (str(telegram_id), 'user', int(datetime.now().timestamp()), username or "", first_name or "")
    )
    # Обновляем username/first_name при каждом взаимодействии
    conn.execute(
        "UPDATE accounts SET username=?, first_name=? WHERE telegram_id=?",
        (username or "", first_name or "", str(telegram_id))
    )
    conn.commit()
    conn.close()


def get_all_users() -> list:
    """Список telegram_id всех зарегистрированных пользователей."""
    conn = get_db()
    rows = conn.execute("SELECT telegram_id FROM accounts").fetchall()
    conn.close()
    return [r["telegram_id"] for r in rows]


def create_auth_token(telegram_id: str) -> str:
    """Создаёт 6-значный код для входа на dashboard (TTL 5 мин)."""
    token   = str(random.randint(100000, 999999))
    expires = int(datetime.now().timestamp()) + 300
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO auth_tokens VALUES (?,?,?)",
        (token, str(telegram_id), expires)
    )
    conn.commit()
    conn.close()
    return token


def load_config() -> dict:
    conn = get_db()
    def gcfg(key, default):
        row = conn.execute("SELECT value FROM bot_config WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default
    cfg = {
        "CHECK_INTERVAL":      int(gcfg("CHECK_INTERVAL",      300)),
        "SPIKE_THRESHOLD_1H":  float(gcfg("SPIKE_THRESHOLD_1H",  15)),
        "SPIKE_THRESHOLD_24H": float(gcfg("SPIKE_THRESHOLD_24H", 30)),
        "DROP_THRESHOLD_1H":   float(gcfg("DROP_THRESHOLD_1H",  -10)),
        "DROP_THRESHOLD_24H":  float(gcfg("DROP_THRESHOLD_24H", -20)),
        "MIN_VOLUME":          int(gcfg("MIN_VOLUME",             5)),
        "CURRENCY":            int(gcfg("CURRENCY",               1)),
    }
    conn.close()
    return cfg


def collect_all_items() -> dict:
    """
    Собирает все скины для мониторинга: watchlist + инвентари.
    Возвращает {name: {name, appid, owners: set(telegram_id)}}
    """
    conn = get_db()
    items: dict = {}

    # Watchlist (только пользователи с включёнными уведомлениями watchlist)
    rows = conn.execute("""
        SELECT DISTINCT w.name, w.appid, w.chat_id
        FROM watchlist w
        LEFT JOIN accounts a ON a.telegram_id = w.chat_id
        WHERE w.chat_id != '' AND w.name != ''
          AND COALESCE(a.notif_watchlist, 1) = 1
    """).fetchall()
    for r in rows:
        n = r["name"]
        if n not in items:
            items[n] = {"name": n, "appid": r["appid"] or 730, "owners": set()}
        items[n]["owners"].add(r["chat_id"])

    # Инвентари (только с включёнными уведомлениями инвентаря)
    rows = conn.execute("""
        SELECT DISTINCT ui.item_name AS name, ui.appid, ui.chat_id
        FROM user_items ui
        LEFT JOIN accounts a ON a.telegram_id = ui.chat_id
        WHERE ui.item_name != '' AND COALESCE(ui.notify, 1) = 1
          AND COALESCE(a.notif_inventory, 1) = 1
    """).fetchall()
    for r in rows:
        n = r["name"]
        if n not in items:
            items[n] = {"name": n, "appid": r["appid"] or 730, "owners": set()}
        items[n]["owners"].add(r["chat_id"])

    conn.close()
    return items


def save_price(item: str, price: float, volume: int, currency: int):
    conn = get_db()
    conn.execute(
        "INSERT INTO prices VALUES (?,?,?,?,?)",
        (item, price, volume, currency, int(datetime.now().timestamp()))
    )
    conn.commit()
    conn.close()


def get_price_ago(item: str, seconds_ago: int, currency: int):
    cutoff = int(datetime.now().timestamp()) - seconds_ago
    conn = get_db()
    row = conn.execute(
        """SELECT price FROM prices
           WHERE item=? AND currency=? AND timestamp<=?
           ORDER BY timestamp DESC LIMIT 1""",
        (item, currency, cutoff)
    ).fetchone()
    conn.close()
    return row["price"] if row else None


def purge_old_prices():
    cutoff = int((datetime.now() - timedelta(days=35)).timestamp())
    conn = get_db()
    conn.execute("DELETE FROM prices WHERE timestamp<?", (cutoff,))
    conn.commit()
    conn.close()


def get_new_trade_offers() -> list:
    """Возвращает pending-офферы, о которых ещё не уведомляли."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT tf.id, tf.trade_id, tf.offerer_id, tf.note, tf.created_at,
                   t.owner_id
            FROM trade_offers tf
            JOIN  trades t          ON t.id  = tf.trade_id
            LEFT JOIN notified_offers no ON no.offer_id = tf.id
            WHERE tf.status = 'pending' AND no.offer_id IS NULL
        """).fetchall()
        result = [dict(r) for r in rows]
    except Exception:
        result = []
    conn.close()
    return result


def get_offer_items(offer_id: int) -> list:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT item_name FROM trade_offer_items WHERE offer_id=?", (offer_id,)
        ).fetchall()
        result = [r["item_name"] for r in rows]
    except Exception:
        result = []
    conn.close()
    return result


def mark_offer_notified(offer_id: int):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO notified_offers VALUES (?,?)",
        (offer_id, int(datetime.now().timestamp()))
    )
    conn.commit()
    conn.close()


# ─── Данные пользователя ──────────────────────────────────────────────────────

def get_user_watchlist(chat_id: str) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT name, rarity FROM watchlist WHERE chat_id=? ORDER BY added_at DESC",
        (chat_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_user_inventory_count(chat_id: str) -> int:
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM user_items WHERE chat_id=?", (chat_id,)
    ).fetchone()
    conn.close()
    return row["c"] if row else 0


def get_user_info(chat_id: str) -> dict:
    conn = get_db()
    row = conn.execute(
        "SELECT username, first_name, role FROM accounts WHERE telegram_id=?", (chat_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


# ─── Навигационное меню (нижняя клавиатура) ───────────────────────────────────

# Метки кнопок — используются и для создания клавиатуры, и для роутинга
BTN_WATCHLIST  = "📋 Watchlist"
BTN_INVENTORY  = "🎒 Инвентарь"
BTN_LOGIN      = "🔑 Войти в панель"
BTN_SETTINGS   = "⚙️ Настройки"
BTN_HELP       = "❓ Помощь"


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_WATCHLIST),  KeyboardButton(BTN_INVENTORY)],
            [KeyboardButton(BTN_LOGIN)],
            [KeyboardButton(BTN_SETTINGS),   KeyboardButton(BTN_HELP)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


# ─── Steam API ────────────────────────────────────────────────────────────────

STEAM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://steamcommunity.com/market/",
}

# Задержка между запросами (сек): base ± jitter
STEAM_DELAY_BASE   = 4.0
STEAM_DELAY_JITTER = 2.0

# При 429/503: начальная пауза и максимальное количество retry
STEAM_BACKOFF_START = 30   # сек
STEAM_BACKOFF_MAX   = 300  # сек

# Авто-обновление инвентарей: интервал и минимальное время между синками одного юзера
INVENTORY_SYNC_INTERVAL = 6 * 3600   # запускать цикл каждые 6 часов
INVENTORY_SYNC_MIN_AGE  = 6 * 3600   # не обновлять если синхронизировали < 6ч назад


async def fetch_price(session: aiohttp.ClientSession, item_name: str, appid: int, currency: int):
    url    = "https://steamcommunity.com/market/priceoverview/"
    params = {"appid": appid, "currency": currency, "market_hash_name": item_name}
    backoff = STEAM_BACKOFF_START

    for attempt in range(4):
        try:
            async with session.get(
                url, params=params,
                headers=STEAM_HEADERS,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 429 or resp.status == 503:
                    wait = min(backoff * (2 ** attempt), STEAM_BACKOFF_MAX)
                    wait += random.uniform(0, 10)
                    print(f"[price] Steam rate limit ({resp.status}), ждём {wait:.0f}с → {item_name}")
                    await asyncio.sleep(wait)
                    continue
                if resp.status != 200:
                    print(f"[price] HTTP {resp.status} для {item_name}")
                    return None, None
                data = await resp.json(content_type=None)
                if data and data.get("success"):
                    price_str  = re.sub(r'[^\d,.]', '', data.get("lowest_price", "0")).strip()
                    if ',' in price_str and '.' in price_str:
                        price_str = price_str.replace(',', '')
                    elif ',' in price_str:
                        price_str = price_str.replace(',', '.')
                    volume_str = re.sub(r'[^\d]', '', data.get("volume", "0"))
                    return float(price_str or 0), int(volume_str or 0)
                return None, None
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            print(f"[price] {item_name} (попытка {attempt+1}): {e}")
            if attempt < 3:
                await asyncio.sleep(random.uniform(5, 15))
        except Exception as e:
            print(f"[price] {item_name}: {e}")
            return None, None
    return None, None


# ─── Форматирование ───────────────────────────────────────────────────────────

def fmt(price: float, currency: int) -> str:
    sym = CURRENCY_SYMBOL.get(currency, "$")
    if currency in (5, 18, 37):
        return f"{price:,.0f} {sym}"
    return f"{sym}{price:,.2f}"


# ─── Команды ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    chat_id = str(update.effective_chat.id)
    register_user(chat_id, username=user.username or "", first_name=user.first_name or "")
    name = user.first_name or user.username or "друг"
    await update.message.reply_text(
        f"👋 <b>Привет, {name}!</b>\n\n"
        "Я бот для отслеживания CS2 скинов.\n"
        "Используй кнопки меню снизу для навигации.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )


async def cmd_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    chat_id = str(update.effective_chat.id)
    register_user(chat_id, username=user.username or "", first_name=user.first_name or "")
    token = create_auth_token(chat_id)
    await update.message.reply_text(
        "🔑 <b>Код для входа в панель:</b>\n\n"
        f"<code>{token}</code>\n\n"
        "⏱ Действителен <b>5 минут</b>.\n\n"
        "Введи этот код на странице:\n"
        "<code>http://localhost:5000/login</code>",
        parse_mode="HTML"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 <b>Помощь:</b>\n\n"
        "<b>Команды:</b>\n"
        "/start — регистрация / главное меню\n"
        "/login — код для входа в панель\n"
        "/help — это сообщение\n\n"
        "<b>Автоматические уведомления:</b>\n"
        "• 📈 Скачки / 📉 просадки цен на скины из watchlist\n"
        "• 📈 Скачки / 📉 просадки цен на скины из инвентаря\n"
        "• 🤝 Новые входящие предложения обмена\n\n"
        "Управление через панель: <code>http://localhost:5000</code>",
        parse_mode="HTML"
    )


# ─── Обработчик кнопок нижнего меню ──────────────────────────────────────────

async def handle_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text    = update.message.text
    chat_id = str(update.effective_chat.id)
    user    = update.effective_user

    if text == BTN_WATCHLIST:
        items = get_user_watchlist(chat_id)
        if items:
            lines  = "\n".join(f"• {i['name']}" for i in items[:20])
            suffix = f"\n…и ещё {len(items) - 20}" if len(items) > 20 else ""
            reply  = f"📋 <b>Watchlist</b> ({len(items)} скинов)\n\n{lines}{suffix}"
        else:
            reply = "📋 <b>Watchlist пуст.</b>\nДобавь скины через веб-панель."

    elif text == BTN_INVENTORY:
        count = get_user_inventory_count(chat_id)
        if count:
            reply = f"🎒 <b>Инвентарь</b>: {count} предметов отслеживается.\n\nПодробнее — в веб-панели."
        else:
            reply = "🎒 <b>Инвентарь не привязан.</b>\nПерейди в панель → Мой инвентарь и добавь Steam-профиль."

    elif text == BTN_LOGIN:
        register_user(chat_id, username=user.username or "", first_name=user.first_name or "")
        token = create_auth_token(chat_id)
        reply = (
            "🔑 <b>Код для входа в панель:</b>\n\n"
            f"<code>{token}</code>\n\n"
            "⏱ Действителен <b>5 минут</b>.\n\n"
            "Введи этот код на странице:\n"
            "<code>http://localhost:5000/login</code>"
        )

    elif text == BTN_SETTINGS:
        cfg = load_config()
        sym = CURRENCY_SYMBOL.get(cfg["CURRENCY"], "$")
        reply = (
            "⚙️ <b>Текущие настройки:</b>\n\n"
            f"• Интервал проверки: <b>{cfg['CHECK_INTERVAL'] // 60} мин</b>\n"
            f"• Валюта: <b>{sym}</b>\n"
            f"• Рост за 1ч:  <b>+{cfg['SPIKE_THRESHOLD_1H']}%</b>\n"
            f"• Падение 1ч:  <b>{cfg['DROP_THRESHOLD_1H']}%</b>\n"
            f"• Рост за 24ч: <b>+{cfg['SPIKE_THRESHOLD_24H']}%</b>\n"
            f"• Падение 24ч: <b>{cfg['DROP_THRESHOLD_24H']}%</b>\n"
            f"• Мин. объём:  <b>{cfg['MIN_VOLUME']}</b>\n\n"
            "Изменить настройки: веб-панель → Настройки"
        )

    elif text == BTN_HELP:
        reply = (
            "📖 <b>Помощь:</b>\n\n"
            "<b>Команды:</b>\n"
            "/start — перезапустить меню\n"
            "/login — код для входа в панель\n"
            "/help — это сообщение\n\n"
            "<b>Автоматические уведомления:</b>\n"
            "• 📈 Скачки / 📉 просадки цен на скины из watchlist\n"
            "• 📈 Скачки / 📉 просадки цен на скины из инвентаря\n"
            "• 🤝 Новые входящие предложения обмена\n\n"
            "Управление через панель: <code>http://localhost:5000</code>"
        )

    else:
        return  # игнорируем прочие текстовые сообщения

    await update.message.reply_text(reply, parse_mode="HTML")


# ─── Алерты ──────────────────────────────────────────────────────────────────

async def send_price_alert(
    bot, owners: set, item_name: str,
    current: float, old: float, pct: float,
    period: str, is_drop: bool, currency: int
):
    icon = "📉" if is_drop else "🚀"
    word = "Просадка" if is_drop else "Скачок"
    encoded = item_name.replace(" ", "%20").replace("|", "%7C")
    text = (
        f"{icon} <b>{word} цены!</b>\n\n"
        f"<b>{item_name}</b>\n"
        f"За: <b>{period}</b>\n"
        f"Было: <b>{fmt(old, currency)}</b> → Стало: <b>{fmt(current, currency)}</b>\n"
        f"Изменение: <b>{pct:+.1f}%</b>\n\n"
        f'<a href="https://steamcommunity.com/market/listings/730/{encoded}">Steam Market</a>'
    )
    for uid in owners:
        try:
            await bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
        except Exception as e:
            print(f"[alert] {uid}: {e}")


async def send_trade_offer_alert(
    bot, owner_id: str, trade_id: int,
    offerer_id: str, items: list, note: str
):
    items_text = "\n".join(f"  • {i}" for i in items) if items else "  —"
    text = (
        "🤝 <b>Новое предложение обмена!</b>\n\n"
        f"К заявке <b>#{trade_id}</b>\n"
        f"От: <code>{offerer_id}</code>\n\n"
        f"Предлагает:\n{items_text}"
    )
    if note:
        text += f"\n\nПримечание: {note}"
    text += "\n\n<a href=\"http://localhost:5000\">Открыть панель</a>"
    try:
        await bot.send_message(chat_id=owner_id, text=text, parse_mode="HTML")
    except Exception as e:
        print(f"[trade alert] {owner_id}: {e}")


# ─── Мониторинг цен ───────────────────────────────────────────────────────────

async def price_monitor(bot):
    last_purge = datetime.now().date()

    while True:
        try:
            cfg           = load_config()
            CURRENCY      = cfg["CURRENCY"]
            CHECK_INTERVAL = cfg["CHECK_INTERVAL"]
            SPIKE_1H      = cfg["SPIKE_THRESHOLD_1H"]
            SPIKE_24H     = cfg["SPIKE_THRESHOLD_24H"]
            DROP_1H       = cfg["DROP_THRESHOLD_1H"]
            DROP_24H      = cfg["DROP_THRESHOLD_24H"]
            MIN_VOL       = cfg["MIN_VOLUME"]

            all_items = collect_all_items()
            print(f"[{datetime.now():%H:%M:%S}] Цены: {len(all_items)} скинов, валюта={CURRENCY}")

            async with aiohttp.ClientSession() as session:
                for name, item in all_items.items():
                    price, volume = await fetch_price(session, name, item["appid"], CURRENCY)
                    if not price:
                        await asyncio.sleep(STEAM_DELAY_BASE + random.uniform(0, STEAM_DELAY_JITTER))
                        continue

                    price_1h  = get_price_ago(name, 3600,  CURRENCY)
                    price_24h = get_price_ago(name, 86400, CURRENCY)
                    save_price(name, price, volume, CURRENCY)

                    if volume < MIN_VOL:
                        await asyncio.sleep(STEAM_DELAY_BASE + random.uniform(0, STEAM_DELAY_JITTER))
                        continue

                    now_ts = datetime.now().timestamp()
                    for old, period, spike_thr, drop_thr in [
                        (price_1h,  "1 час",   SPIKE_1H,  DROP_1H),
                        (price_24h, "24 часа", SPIKE_24H, DROP_24H),
                    ]:
                        if not old or old <= 0:
                            continue
                        pct_val  = ((price - old) / old) * 100
                        is_drop  = pct_val <= drop_thr
                        is_spike = pct_val >= spike_thr
                        if not is_spike and not is_drop:
                            continue

                        # Кулдаун и рассылка — независимо для каждого пользователя
                        for owner_id in item["owners"]:
                            ck = (name, period, owner_id)
                            if now_ts - _alerted.get(ck, 0) < ALERT_COOLDOWN:
                                continue
                            _alerted[ck] = now_ts
                            await send_price_alert(
                                bot, {owner_id}, name,
                                price, old, pct_val, period, is_drop, CURRENCY
                            )

                    await asyncio.sleep(STEAM_DELAY_BASE + random.uniform(0, STEAM_DELAY_JITTER))

            today = datetime.now().date()
            if today > last_purge:
                purge_old_prices()
                last_purge = today
                print("БД: старые записи удалены")

            print(f"Следующая проверка цен через {CHECK_INTERVAL // 60} мин.")

        except Exception as e:
            print(f"[price_monitor] Ошибка: {e}")

        await asyncio.sleep(cfg.get("CHECK_INTERVAL", 300))


# ─── Мониторинг торговых предложений ─────────────────────────────────────────

async def trade_monitor(bot):
    while True:
        try:
            offers = get_new_trade_offers()
            for offer in offers:
                items = get_offer_items(offer["id"])
                await send_trade_offer_alert(
                    bot,
                    owner_id=offer["owner_id"],
                    trade_id=offer["trade_id"],
                    offerer_id=offer["offerer_id"],
                    items=items,
                    note=offer.get("note") or "",
                )
                mark_offer_notified(offer["id"])
                print(f"[trade] Уведомление о предложении #{offer['id']} → {offer['owner_id']}")
        except Exception as e:
            print(f"[trade_monitor] Ошибка: {e}")

        await asyncio.sleep(60)


# ─── Монитор исходящих уведомлений (принятые трейды и др.) ───────────────────

async def notification_monitor(bot):
    while True:
        try:
            conn = get_db()
            rows = conn.execute(
                "SELECT id, chat_id, message FROM pending_tg_notifications WHERE sent=0 ORDER BY created_at"
            ).fetchall()
            for row in rows:
                try:
                    await bot.send_message(chat_id=row["chat_id"], text=row["message"], parse_mode="HTML")
                    conn.execute("UPDATE pending_tg_notifications SET sent=1 WHERE id=?", (row["id"],))
                    conn.commit()
                    print(f"[notify] Отправлено уведомление #{row['id']} → {row['chat_id']}")
                except Exception as e:
                    print(f"[notify] Ошибка отправки #{row['id']}: {e}")
            conn.close()
        except Exception as e:
            print(f"[notification_monitor] Ошибка: {e}")
        await asyncio.sleep(10)


# ─── Авто-обновление инвентарей ──────────────────────────────────────────────

async def fetch_inventory_async(session: aiohttp.ClientSession, steam_id64: str) -> tuple:
    """Async версия _fetch_inventory из dashboard.py."""
    url    = f"https://steamcommunity.com/inventory/{steam_id64}/730/2"
    params = {"l": "english", "count": 500}
    try:
        async with session.get(url, params=params, headers=STEAM_HEADERS,
                               timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status == 429:
                return None, "rate_limit"
            if resp.status != 200:
                return None, f"HTTP {resp.status}"
            data = await resp.json(content_type=None)

        if not data.get("success"):
            return None, "closed"

        descriptions = {
            f"{d['classid']}_{d['instanceid']}": d
            for d in data.get("descriptions", [])
        }
        items = []
        seen  = set()
        for asset in data.get("assets", []):
            key  = f"{asset['classid']}_{asset['instanceid']}"
            desc = descriptions.get(key, {})
            name = desc.get("market_hash_name")
            if not name or name in seen:
                continue
            if desc.get("marketable", 0) == 1:
                rarity = rarity_color = item_type = ""
                for tag in desc.get("tags", []):
                    cat = tag.get("category", "")
                    if cat == "Rarity":
                        rarity       = tag.get("internal_name", "")
                        rarity_color = tag.get("color", "")
                    elif cat == "Type":
                        item_type = tag.get("internal_name", "")
                items.append({
                    "name": name, "appid": 730,
                    "rarity": rarity, "rarity_color": rarity_color,
                    "item_type": item_type, "icon_url": desc.get("icon_url", "")
                })
                seen.add(name)
        return items, None
    except Exception as e:
        return None, str(e)


async def inventory_monitor(bot):
    """Каждые INVENTORY_SYNC_INTERVAL часов обновляет инвентари всех юзеров."""
    while True:
        await asyncio.sleep(INVENTORY_SYNC_INTERVAL)
        try:
            conn  = get_db()
            now   = int(datetime.now().timestamp())
            users = conn.execute(
                "SELECT chat_id, steam_id FROM users WHERE steam_id IS NOT NULL AND steam_id != ''"
            ).fetchall()
            conn.close()

            print(f"[inventory] Авто-обновление: {len(users)} аккаунтов")
            async with aiohttp.ClientSession() as session:
                for user in users:
                    conn = get_db()
                    row  = conn.execute(
                        "SELECT last_synced FROM users WHERE chat_id=?", (user["chat_id"],)
                    ).fetchone()
                    last = row["last_synced"] if row and row["last_synced"] else 0
                    conn.close()

                    if now - last < INVENTORY_SYNC_MIN_AGE:
                        continue

                    items, err = await fetch_inventory_async(session, user["steam_id"])
                    if err == "rate_limit":
                        print(f"[inventory] Rate limit, пауза 60с")
                        await asyncio.sleep(60)
                        continue
                    if err or not items:
                        print(f"[inventory] {user['chat_id']}: {err}")
                        await asyncio.sleep(2)
                        continue

                    conn = get_db()
                    conn.execute("DELETE FROM user_items WHERE chat_id=?", (user["chat_id"],))
                    for item in items:
                        conn.execute(
                            "INSERT OR IGNORE INTO user_items VALUES (?,?,?,?,1)",
                            (user["chat_id"], item["name"], item["appid"], now)
                        )
                        conn.execute(
                            "INSERT OR REPLACE INTO item_rarity VALUES (?,?,?,?,?)",
                            (item["name"], item.get("rarity", ""), item.get("rarity_color", ""),
                             item.get("item_type", ""), item.get("icon_url", ""))
                        )
                    conn.execute(
                        "UPDATE users SET last_synced=? WHERE chat_id=?", (now, user["chat_id"])
                    )
                    conn.commit()
                    conn.close()
                    print(f"[inventory] {user['chat_id']}: {len(items)} предметов обновлено")
                    await asyncio.sleep(STEAM_DELAY_BASE + random.uniform(0, STEAM_DELAY_JITTER))

        except Exception as e:
            print(f"[inventory_monitor] Ошибка: {e}")


# ─── Запуск ───────────────────────────────────────────────────────────────────

async def main():
    init_db()

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("login", cmd_login))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_button))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    print("✅ Бот запущен!")
    print("   Команды: /start  /login  /help")
    print("   Мониторинг: цены + торговые предложения")

    await asyncio.gather(
        price_monitor(app.bot),
        trade_monitor(app.bot),
        notification_monitor(app.bot),
        inventory_monitor(app.bot),
    )


if __name__ == "__main__":
    asyncio.run(main())
