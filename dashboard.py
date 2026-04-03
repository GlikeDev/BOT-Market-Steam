from flask import Flask, jsonify, request, send_from_directory, send_file, Response, session, redirect
import sqlite3
import json
import os
import re
import urllib.parse
import urllib.request
import urllib.error
import time
import gzip
import threading
from datetime import datetime, timedelta
from functools import wraps
import secrets as pysecrets

app = Flask(__name__)
DB_PATH = "prices.db"
SKIN_IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skin_images")
os.makedirs(SKIN_IMG_DIR, exist_ok=True)

# Локи для дедупликации одновременных запросов иконок одного предмета.
# _icon_locks_mu защищает сам словарь при конкурентном создании новых локов.
_icon_locks: dict[str, threading.Lock] = {}
_icon_locks_mu = threading.Lock()

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            item TEXT, price REAL, volume INTEGER,
            currency INTEGER, timestamp INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            chat_id TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL,
            appid INTEGER,
            added_at INTEGER,
            rarity TEXT,
            rarity_color TEXT,
            PRIMARY KEY (chat_id, name)
        )
    """)
    for col in ("rarity TEXT", "rarity_color TEXT"):
        try:
            conn.execute(f"ALTER TABLE watchlist ADD COLUMN {col}")
        except Exception:
            pass
    # Миграция: добавляем chat_id если таблица старая (без него)
    wl_cols = [r[1] for r in conn.execute("PRAGMA table_info(watchlist)").fetchall()]
    if 'chat_id' not in wl_cols:
        conn.execute("ALTER TABLE watchlist ADD COLUMN chat_id TEXT NOT NULL DEFAULT ''")
        conn.commit()
    try:
        conn.execute("ALTER TABLE item_rarity ADD COLUMN item_type TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE item_rarity ADD COLUMN icon_url TEXT DEFAULT ''")
    except Exception:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id TEXT PRIMARY KEY, steam_url TEXT,
            steam_id TEXT, added_at INTEGER,
            last_synced INTEGER DEFAULT 0
        )
    """)
    for col in ("last_synced INTEGER DEFAULT 0", "avatar_url TEXT DEFAULT ''", "persona_name TEXT DEFAULT ''"):
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col}")
        except Exception:
            pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_items (
            chat_id TEXT, item_name TEXT, appid INTEGER, added_at INTEGER,
            notify INTEGER DEFAULT 1,
            PRIMARY KEY (chat_id, item_name)
        )
    """)
    try:
        conn.execute("ALTER TABLE user_items ADD COLUMN notify INTEGER DEFAULT 1")
    except Exception:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_config (
            key TEXT PRIMARY KEY, value TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history_imported (
            item TEXT PRIMARY KEY,
            imported_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS item_rarity (
            name TEXT PRIMARY KEY,
            rarity TEXT,
            rarity_color TEXT,
            item_type TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS auth_tokens (
            token TEXT PRIMARY KEY,
            telegram_id TEXT,
            expires_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            telegram_id TEXT PRIMARY KEY,
            role TEXT DEFAULT 'user',
            created_at INTEGER,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT ''
        )
    """)
    for col in ("username TEXT DEFAULT ''", "first_name TEXT DEFAULT ''",
                "display_name TEXT DEFAULT ''", "trade_link TEXT DEFAULT ''",
                "trade_link_public INTEGER DEFAULT 0",
                "verified INTEGER DEFAULT 0",
                "banned INTEGER DEFAULT 0",
                "notif_inventory INTEGER DEFAULT 1",
                "notif_watchlist INTEGER DEFAULT 1",
                "notif_reports INTEGER DEFAULT 1"):
        try:
            conn.execute(f"ALTER TABLE accounts ADD COLUMN {col}")
        except Exception:
            pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            note TEXT DEFAULT '',
            created_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            appid INTEGER DEFAULT 730
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_wants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL,
            item_name TEXT,
            appid INTEGER DEFAULT 730
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL,
            offerer_id TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            note TEXT DEFAULT '',
            created_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_offer_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offer_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            appid INTEGER DEFAULT 730
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_tg_notifications (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id    TEXT    NOT NULL,
            message    TEXT    NOT NULL,
            sent       INTEGER DEFAULT 0,
            created_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id TEXT    NOT NULL,
            subject     TEXT    NOT NULL,
            message     TEXT    NOT NULL,
            created_at  INTEGER NOT NULL,
            is_read     INTEGER DEFAULT 0
        )
    """)
    for col in ("status TEXT DEFAULT 'pending'",):
        try:
            conn.execute(f"ALTER TABLE reports ADD COLUMN {col}")
        except Exception:
            pass
    # Генерируем секретный ключ один раз
    row = conn.execute("SELECT value FROM bot_config WHERE key='SECRET_KEY'").fetchone()
    if not row:
        key = pysecrets.token_hex(32)
        conn.execute("INSERT INTO bot_config VALUES (?,?)", ("SECRET_KEY", key))
    conn.commit()
    conn.close()

def setup_secret():
    conn = get_db()
    row = conn.execute("SELECT value FROM bot_config WHERE key='SECRET_KEY'").fetchone()
    conn.close()
    app.secret_key = row["value"] if row else pysecrets.token_hex(32)

def get_config(key, default=None):
    conn = get_db()
    row = conn.execute("SELECT value FROM bot_config WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default

def set_config(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO bot_config VALUES (?,?)", (key, str(value)))
    conn.commit()
    conn.close()

def esc_html(s):
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

# --- Auth ---
AUTH_DISABLED = False
DEV_TOKEN = "claude-dev-2026"  # токен для dev-входа

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if AUTH_DISABLED:
            session['telegram_id'] = '853299211'
            session['role'] = 'admin'
            return f(*args, **kwargs)
        if not session.get('telegram_id'):
            if request.path.startswith('/api/'):
                return jsonify({"error": "Не авторизован"}), 401
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if AUTH_DISABLED:
            session['telegram_id'] = '853299211'
            session['role'] = 'admin'
            return f(*args, **kwargs)
        if not session.get('telegram_id'):
            if request.path.startswith('/api/'):
                return jsonify({"error": "Не авторизован"}), 401
            return redirect('/login')
        if session.get('role') != 'admin':
            return jsonify({"error": "Нет прав"}), 403
        return f(*args, **kwargs)
    return decorated

# --- Steam sync helpers ---

def _extract_steam_id(url):
    url = url.strip().rstrip("/")
    m = re.search(r'/profiles/(\d{17})', url)
    if m:
        return m.group(1), "id64"
    m = re.search(r'/id/([^/]+)', url)
    if m:
        return m.group(1), "vanity"
    return None, None

def _resolve_vanity(vanity):
    try:
        url = f"https://steamcommunity.com/id/{vanity}/?xml=1"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode()
            m = re.search(r'<steamID64>(\d+)</steamID64>', text)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None

def _fetch_inventory(steam_id64):
    params  = urllib.parse.urlencode({"l": "english", "count": 500})
    url     = f"https://steamcommunity.com/inventory/{steam_id64}/730/2?{params}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    def _do_request():
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())

    try:
        try:
            data = _do_request()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                # Одна повторная попытка через 5 секунд
                retry_after = int(e.headers.get("Retry-After", 5))
                wait = min(retry_after, 8)  # ждём не больше 8 с в веб-запросе
                time.sleep(wait)
                try:
                    data = _do_request()
                except urllib.error.HTTPError as e2:
                    if e2.code == 429:
                        return None, (
                            "Steam ограничивает запросы (429 Too Many Requests). "
                            "Подождите 1–2 минуты и попробуйте снова."
                        )
                    return None, f"Steam ошибка {e2.code}"
            else:
                return None, f"Steam ошибка {e.code}"

        if not data.get("success"):
            return None, "Steam вернул ошибку (инвентарь закрыт или не существует)"

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
                icon_url = desc.get("icon_url", "")
                items.append({"name": name, "appid": 730,
                               "rarity": rarity, "rarity_color": rarity_color,
                               "item_type": item_type, "icon_url": icon_url})
                seen.add(name)
        return items, None

    except Exception as e:
        return None, str(e)

def _get_or_fetch_icon(item_name, appid=730, conn=None):
    """Возвращает icon_url для предмета: сначала из БД, иначе с листинга Steam.
    Работает для любых предметов включая редкие (Dragon Lore и т.д.).
    Если icon_url получен с Steam — сохраняет в item_rarity для кэша.
    conn — опциональное существующее соединение (не закрывает его).

    При одновременных запросах одного предмета от разных юзеров — только
    один поток идёт в Steam, остальные ждут и получают результат из DB."""
    close_conn = conn is None
    if conn is None:
        conn = get_db()

    # Быстрая проверка до взятия лока
    try:
        row = conn.execute("SELECT icon_url FROM item_rarity WHERE name=?", (item_name,)).fetchone()
        if row and row["icon_url"]:
            return row["icon_url"]
    except Exception:
        if close_conn:
            conn.close()
        return ""

    # Получаем (или создаём) лок для этого предмета
    with _icon_locks_mu:
        if item_name not in _icon_locks:
            _icon_locks[item_name] = threading.Lock()
        lock = _icon_locks[item_name]

    with lock:
        # Повторная проверка DB — пока мы ждали лок, другой поток уже мог сохранить
        try:
            row = conn.execute("SELECT icon_url FROM item_rarity WHERE name=?", (item_name,)).fetchone()
            if row and row["icon_url"]:
                return row["icon_url"]

            encoded = urllib.parse.quote(item_name)

            # Способ 1: render endpoint — быстро, но возвращает пустой assets
            # если активных листингов нет (редкие/дорогие предметы типа Dragon Lore)
            icon = ""
            try:
                params = urllib.parse.urlencode({"start": 0, "count": 1, "currency": 1, "language": "english", "country": "US"})
                url    = f"https://steamcommunity.com/market/listings/{appid}/{encoded}/render?{params}"
                req    = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                for app_assets in data.get("assets", {}).values():
                    for ctx_assets in app_assets.values():
                        for asset in ctx_assets.values():
                            icon = asset.get("icon_url", "")
                            if icon:
                                break
                        if icon:
                            break
                    if icon:
                        break
            except Exception:
                pass

            # Способ 2: парсим HTML страницы листинга — работает всегда,
            # icon_url есть в JS-переменных даже при 0 активных листингов
            if not icon:
                try:
                    url = f"https://steamcommunity.com/market/listings/{appid}/{encoded}"
                    req = urllib.request.Request(url, headers={
                        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept-Language": "en-US,en;q=0.9",
                    })
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        html = resp.read().decode("utf-8", errors="ignore")
                    m = re.search(r'"icon_url"\s*:\s*"([^"]+)"', html)
                    if m:
                        icon = m.group(1)
                except Exception:
                    pass

            if icon:
                conn.execute(
                    "INSERT INTO item_rarity(name, rarity, rarity_color, item_type, icon_url) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(name) DO UPDATE SET icon_url=excluded.icon_url",
                    (item_name, "", "", "", icon)
                )
                conn.commit()
            return icon
        except Exception:
            return ""
        finally:
            if close_conn:
                conn.close()

# --- Routes ---

@app.route("/")
@login_required
def index():
    return send_from_directory(".", "dashboard.html")

@app.route("/login")
def login_page():
    if session.get('telegram_id'):
        return redirect('/')
    return send_from_directory(".", "login.html")

REACT_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "react-dist")

@app.route("/app/assets/<path:filename>")
def react_assets(filename):
    return send_from_directory(os.path.join(REACT_DIST, "assets"), filename)

@app.route("/app/<path:filename>")
def react_static(filename):
    return send_from_directory(REACT_DIST, filename)

# --- Auth API ---

@app.route("/api/auth/verify", methods=["POST"])
def api_auth_verify():
    code = str(request.json.get("code", "")).strip()
    conn = get_db()
    now = int(datetime.now().timestamp())
    row = conn.execute(
        "SELECT telegram_id FROM auth_tokens WHERE token=? AND expires_at > ?",
        (code, now)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "Неверный или устаревший код"}), 400

    telegram_id = row["telegram_id"]
    conn.execute("DELETE FROM auth_tokens WHERE token=?", (code,))

    account = conn.execute(
        "SELECT role FROM accounts WHERE telegram_id=?", (telegram_id,)
    ).fetchone()
    if not account:
        admin_exists = conn.execute("SELECT 1 FROM accounts WHERE role='admin'").fetchone()
        role = "admin" if not admin_exists else "user"
        conn.execute(
            "INSERT INTO accounts VALUES (?,?,?)",
            (telegram_id, role, now)
        )
    else:
        role = account["role"]

    conn.commit()
    conn.close()

    session.permanent = True
    session['telegram_id'] = telegram_id
    session['role'] = role
    return jsonify({"ok": True, "role": role})

@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/dev-login")
def dev_login():
    """Dev bypass login — requires secret token in query string."""
    if request.args.get("token") != DEV_TOKEN:
        return "Forbidden", 403
    session["telegram_id"] = "853299211"
    session["role"] = "admin"
    return redirect("/")

@app.route("/api/auth/me")
def api_auth_me():
    if AUTH_DISABLED:
        return jsonify({"logged_in": True, "telegram_id": "853299211", "role": "admin",
                        "username": "dev", "first_name": "Dev"})
    tid = session.get('telegram_id')
    if not tid:
        return jsonify({"logged_in": False})
    conn = get_db()
    acc  = conn.execute(
        "SELECT username, first_name, role, COALESCE(banned,0) AS banned FROM accounts WHERE telegram_id=?", (tid,)
    ).fetchone()
    user = conn.execute(
        "SELECT avatar_url FROM users WHERE chat_id=?", (tid,)
    ).fetchone()
    conn.close()
    db_role = acc["role"] if acc else session.get('role', 'user')
    session['role'] = db_role
    return jsonify({
        "logged_in":   True,
        "telegram_id": tid,
        "role":        db_role,
        "banned":      acc["banned"] if acc else 0,
        "username":    acc["username"]    if acc  else "",
        "first_name":  acc["first_name"]  if acc  else "",
        "avatar_url":  user["avatar_url"] if user else "",
    })

# --- Profile API ---

INVENTORY_SYNC_TTL = 300  # минимум 5 минут между ручными синхронизациями

@app.route("/api/profile/inventory", methods=["POST"])
@login_required
def api_profile_inventory():
    telegram_id = session['telegram_id']
    steam_url = request.json.get("steam_url", "").strip()
    force     = request.json.get("force", False)
    if not steam_url:
        return jsonify({"ok": False, "error": "Пустая ссылка"}), 400

    steam_id, id_type = _extract_steam_id(steam_url)
    if not steam_id:
        return jsonify({"ok": False, "error": "Неверная ссылка Steam"}), 400

    if id_type == "vanity":
        steam_id = _resolve_vanity(steam_id)
        if not steam_id:
            return jsonify({"ok": False, "error": "Аккаунт не найден"}), 400

    # TTL: не перезапрашивать Steam если синхронизировали недавно
    now = int(datetime.now().timestamp())
    if not force:
        conn = get_db()
        row = conn.execute(
            "SELECT last_synced, chat_id FROM users WHERE chat_id=? AND steam_id=?",
            (telegram_id, steam_id)
        ).fetchone()
        conn.close()
        if row and row["last_synced"] and (now - row["last_synced"]) < INVENTORY_SYNC_TTL:
            count = get_db().execute(
                "SELECT COUNT(*) as c FROM user_items WHERE chat_id=?", (telegram_id,)
            ).fetchone()["c"]
            return jsonify({"ok": True, "count": count, "steam_id": steam_id, "cached": True})

    items, error = _fetch_inventory(steam_id)
    if error:
        return jsonify({"ok": False, "error": error}), 400

    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO users VALUES (?,?,?,?,?)",
        (telegram_id, steam_url, steam_id, now, now)
    )
    conn.execute("DELETE FROM user_items WHERE chat_id=?", (telegram_id,))
    for item in items:
        conn.execute(
            "INSERT OR IGNORE INTO user_items VALUES (?,?,?,?,1)",
            (telegram_id, item["name"], item["appid"], now)
        )
        conn.execute(
            "INSERT OR REPLACE INTO item_rarity VALUES (?,?,?,?,?)",
            (item["name"], item.get("rarity", ""), item.get("rarity_color", ""),
             item.get("item_type", ""), item.get("icon_url", ""))
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "count": len(items), "steam_id": steam_id, "cached": False})

@app.route("/api/profile/inventory", methods=["DELETE"])
@login_required
def api_profile_inventory_unlink():
    telegram_id = session['telegram_id']
    conn = get_db()
    conn.execute("DELETE FROM users      WHERE chat_id=?", (telegram_id,))
    conn.execute("DELETE FROM user_items WHERE chat_id=?", (telegram_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/profile/steam-items")
@login_required
def api_profile_steam_items():
    """Только предметы из привязанного Steam-инвентаря (без watchlist)."""
    telegram_id = session['telegram_id']
    conn = get_db()
    rows = conn.execute("""
        SELECT ui.item_name as name, ui.appid,
               COALESCE(ir.icon_url, '')   as icon_url,
               COALESCE(ir.item_type, '')  as item_type
        FROM user_items ui
        LEFT JOIN item_rarity ir ON ir.name = ui.item_name
        WHERE ui.chat_id=?
        ORDER BY ui.item_name
    """, (telegram_id,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/profile/items")
@login_required
def api_profile_items():
    telegram_id = session['telegram_id']
    conn = get_db()
    rows = conn.execute("""
        SELECT ui.item_name as name, ui.appid,
               COALESCE(NULLIF(w.rarity,''), ir.rarity, '')             as rarity,
               COALESCE(NULLIF(w.rarity_color,''), ir.rarity_color, '') as rarity_color,
               COALESCE(ir.item_type, '')                               as item_type,
               COALESCE(ir.icon_url, '')                                as icon_url,
               COALESCE(ui.notify, 1)                                   as notify
        FROM user_items ui
        LEFT JOIN watchlist w    ON w.name = ui.item_name AND w.chat_id = ui.chat_id
        LEFT JOIN item_rarity ir ON ir.name = ui.item_name
        WHERE ui.chat_id=?
        ORDER BY ui.item_name
    """, (telegram_id,)).fetchall()

    if not rows:
        conn.close()
        return jsonify([])

    now        = int(datetime.now().timestamp())
    cutoff_1h  = now - 3600
    cutoff_24h = now - 86400

    item_names = [r["name"] for r in rows]
    ph         = ','.join('?' * len(item_names))

    def batch_price(cutoff=None, vol_only=False):
        """vol_only=True — только записи бота (volume>0), для актуального объёма."""
        parts  = [f"item IN ({ph})"]
        params = item_names[:]
        if cutoff is not None:
            parts.append("timestamp <= ?")
            params.append(cutoff)
        if vol_only:
            parts.append("volume > 0")
        where = " AND ".join(parts)
        result = {}
        for pr in conn.execute(
            f"SELECT item, price, volume, MAX(timestamp) FROM prices WHERE {where} GROUP BY item",
            params
        ).fetchall():
            result[pr["item"]] = {"price": pr["price"], "volume": pr["volume"]}
        return result

    latest     = batch_price()           # актуальная цена (включая импорт)
    latest_vol = batch_price(vol_only=True)  # объём только из записей бота
    old_1h     = batch_price(cutoff_1h)
    old_24h    = batch_price(cutoff_24h)
    conn.close()

    def pct(cur, old):
        if cur and old and old > 0:
            return round((cur - old) / old * 100, 1)
        return None

    result = []
    for r in rows:
        name     = r["name"]
        price    = latest.get(name, {}).get("price")
        volume   = latest_vol.get(name, {}).get("volume")  # из бот-мониторинга
        p_1h     = old_1h.get(name,  {}).get("price")
        p_24h    = old_24h.get(name, {}).get("price")
        result.append({
            "name":         name,
            "appid":        r["appid"],
            "rarity":       r["rarity"]       or "",
            "rarity_color": r["rarity_color"] or "",
            "item_type":    r["item_type"]    or "",
            "icon_url":     r["icon_url"]     or "",
            "price":        price,
            "volume":       volume,
            "price_1h":     p_1h,
            "price_24h":    p_24h,
            "pct_1h":       pct(price, p_1h),
            "pct_24h":      pct(price, p_24h),
            "notify":       r["notify"] if r["notify"] is not None else 1,
        })
    return jsonify(result)

@app.route("/api/profile/items/notify", methods=["POST"])
@login_required
def api_profile_item_notify():
    """Включает / выключает уведомления для конкретного предмета инвентаря."""
    telegram_id = session['telegram_id']
    data   = request.json or {}
    name   = data.get("name", "").strip()
    notify = 1 if data.get("notify", True) else 0
    if not name:
        return jsonify({"ok": False, "error": "Пустое название"}), 400
    conn = get_db()
    conn.execute(
        "UPDATE user_items SET notify=? WHERE chat_id=? AND item_name=?",
        (notify, telegram_id, name)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "notify": notify})

@app.route("/api/profile/fetch-rarities", methods=["POST"])
@login_required
def api_profile_fetch_rarities():
    """Обновляет редкость предметов через повторный запрос инвентаря Steam."""
    telegram_id = session['telegram_id']
    conn = get_db()

    user = conn.execute(
        "SELECT steam_id FROM users WHERE chat_id=?", (telegram_id,)
    ).fetchone()

    if not user or not user["steam_id"]:
        conn.close()
        return jsonify({"ok": False, "error": "Steam не привязан"})

    items, err = _fetch_inventory(user["steam_id"])
    if err or not items:
        conn.close()
        return jsonify({"ok": False, "error": err or "Пустой инвентарь"})

    updated = 0
    for item in items:
        if item.get("rarity") or item.get("item_type") or item.get("icon_url"):
            conn.execute(
                "INSERT OR REPLACE INTO item_rarity VALUES (?,?,?,?,?)",
                (item["name"], item.get("rarity", ""), item.get("rarity_color", ""),
                 item.get("item_type", ""), item.get("icon_url", ""))
            )
            updated += 1

    conn.commit()

    remaining = conn.execute("""
        SELECT COUNT(*) FROM user_items ui
        LEFT JOIN item_rarity ir ON ir.name = ui.item_name
        WHERE ui.chat_id = ?
          AND (ir.name IS NULL OR (ir.rarity = '' AND ir.rarity_color = ''))
    """, (telegram_id,)).fetchone()[0]

    conn.close()
    return jsonify({"ok": True, "updated": updated, "remaining": remaining})

@app.route("/api/profile/me")
@login_required
def api_profile_me():
    telegram_id = session['telegram_id']
    conn = get_db()
    user = conn.execute(
        "SELECT steam_url, steam_id FROM users WHERE chat_id=?", (telegram_id,)
    ).fetchone()
    items = conn.execute(
        "SELECT item_name, appid FROM user_items WHERE chat_id=? ORDER BY item_name",
        (telegram_id,)
    ).fetchall()
    conn.close()
    return jsonify({
        "telegram_id": telegram_id,
        "steam_url":   user["steam_url"] if user else None,
        "steam_id":    user["steam_id"]  if user else None,
        "items":       [{"name": r["item_name"], "appid": r["appid"]} for r in items],
    })

def _fetch_steam_profile(steam_id64):
    """Fetch avatar_url and persona_name via Steam XML API."""
    url = f"https://steamcommunity.com/profiles/{steam_id64}?xml=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
        avatar = re.search(r"<avatarFull><!\[CDATA\[([^\]]+)\]\]></avatarFull>", body)
        name   = re.search(r"<steamID><!\[CDATA\[([^\]]+)\]\]></steamID>", body)
        return (
            avatar.group(1) if avatar else "",
            name.group(1)   if name   else "",
        )
    except Exception:
        return "", ""


STEAM_OPENID_URL = "https://steamcommunity.com/openid/login"

@app.route("/api/steam/login")
@login_required
def steam_openid_login():
    from flask import url_for
    return_to = url_for("steam_openid_callback", _external=True)
    params = urllib.parse.urlencode({
        "openid.ns":         "http://specs.openid.net/auth/2.0",
        "openid.identity":   "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.mode":       "checkid_setup",
        "openid.return_to":  return_to,
        "openid.realm":      request.host_url,
    })
    return redirect(f"{STEAM_OPENID_URL}?{params}")


@app.route("/api/steam/callback")
@login_required
def steam_openid_callback():
    args = dict(request.args)
    if args.get("openid.mode") != "id_res":
        return redirect("/#steam_error")

    # Verify with Steam
    args["openid.mode"] = "check_authentication"
    data = urllib.parse.urlencode(args).encode()
    req  = urllib.request.Request(STEAM_OPENID_URL, data=data,
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
    except Exception:
        return redirect("/#steam_error")

    if "is_valid:true" not in body:
        return redirect("/#steam_error")

    claimed = request.args.get("openid.claimed_id", "")
    m = re.search(r"/openid/id/(\d{17})", claimed)
    if not m:
        return redirect("/#steam_error")

    steam_id    = m.group(1)
    steam_url   = f"https://steamcommunity.com/profiles/{steam_id}"
    avatar_url, persona_name = _fetch_steam_profile(steam_id)
    tid         = session["telegram_id"]
    now         = int(datetime.now().timestamp())
    conn        = get_db()
    existing = conn.execute(
        "SELECT chat_id FROM users WHERE steam_id=? AND chat_id!=?", (steam_id, tid)
    ).fetchone()
    if existing:
        conn.close()
        return redirect("/#steam_already_linked")
    conn.execute(
        "INSERT INTO users (chat_id, steam_url, steam_id, added_at, last_synced, avatar_url, persona_name) "
        "VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET steam_url=excluded.steam_url, steam_id=excluded.steam_id, "
        "avatar_url=excluded.avatar_url, persona_name=excluded.persona_name",
        (tid, steam_url, steam_id, now, 0, avatar_url, persona_name)
    )
    conn.commit()
    conn.close()

    # Sync inventory in background
    def _sync():
        try:
            items, err = _fetch_inventory(steam_id)
            if items:
                c = get_db()
                c.execute("DELETE FROM user_items WHERE chat_id=?", (tid,))
                for item in items:
                    c.execute(
                        "INSERT INTO user_items (chat_id, item_name, appid) VALUES (?,?,?)",
                        (tid, item["name"], item.get("appid", 730))
                    )
                c.execute("UPDATE users SET last_synced=? WHERE chat_id=?", (now, tid))
                c.commit()
                c.close()
        except Exception:
            pass
    threading.Thread(target=_sync, daemon=True).start()

    return redirect("/#steam_linked")


@app.route("/api/steam/unlink", methods=["POST"])
@login_required
def steam_openid_unlink():
    if session.get("role") not in ("admin", "moderator"):
        return jsonify({"ok": False, "error": "Нет прав"}), 403
    tid = session["telegram_id"]
    conn = get_db()
    conn.execute("DELETE FROM users WHERE chat_id=?", (tid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/profile/account")
@login_required
def api_profile_account():
    tid  = session['telegram_id']
    conn = get_db()
    acc  = conn.execute(
        "SELECT display_name, trade_link, trade_link_public, username, first_name, verified "
        "FROM accounts WHERE telegram_id=?", (tid,)
    ).fetchone()
    user = conn.execute(
        "SELECT steam_id, avatar_url, persona_name FROM users WHERE chat_id=?", (tid,)
    ).fetchone()
    conn.close()
    return jsonify({
        "display_name":      acc["display_name"]      if acc else "",
        "trade_link":        acc["trade_link"]         if acc else "",
        "trade_link_public": acc["trade_link_public"]  if acc else 0,
        "username":          acc["username"]            if acc else "",
        "first_name":        acc["first_name"]          if acc else "",
        "steam_id":          user["steam_id"]           if user else None,
        "avatar_url":        user["avatar_url"]         if user else "",
        "persona_name":      user["persona_name"]       if user else "",
        "verified":          acc["verified"]             if acc else 0,
    })

@app.route("/api/profile/account", methods=["POST"])
@login_required
def api_profile_account_save():
    tid               = session['telegram_id']
    data              = request.json or {}
    display_name      = data.get("display_name", "").strip()[:64]
    trade_link        = data.get("trade_link",   "").strip()[:256]
    trade_link_public = 1 if data.get("trade_link_public") else 0
    conn = get_db()
    conn.execute(
        "UPDATE accounts SET display_name=?, trade_link=?, trade_link_public=? WHERE telegram_id=?",
        (display_name, trade_link, trade_link_public, tid)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/profile/notifications")
@login_required
def api_profile_notifications_get():
    tid = session['telegram_id']
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(notif_inventory,1) AS notif_inventory, "
        "COALESCE(notif_watchlist,1) AS notif_watchlist, "
        "COALESCE(notif_reports,1) AS notif_reports "
        "FROM accounts WHERE telegram_id=?", (tid,)
    ).fetchone()
    conn.close()
    return jsonify(dict(row) if row else {"notif_inventory": 1, "notif_watchlist": 1, "notif_reports": 1})


@app.route("/api/profile/notifications", methods=["POST"])
@login_required
def api_profile_notifications_save():
    tid  = session['telegram_id']
    data = request.json or {}
    ni   = 1 if data.get("notif_inventory") else 0
    nw   = 1 if data.get("notif_watchlist") else 0
    nr   = 1 if data.get("notif_reports")   else 0
    conn = get_db()
    conn.execute(
        "UPDATE accounts SET notif_inventory=?, notif_watchlist=?, notif_reports=? WHERE telegram_id=?",
        (ni, nw, nr, tid)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/user/<telegram_id>/profile")
@login_required
def api_user_profile(telegram_id):
    conn = get_db()
    acc  = conn.execute(
        "SELECT display_name, first_name, username, trade_link, trade_link_public, verified "
        "FROM accounts WHERE telegram_id=?", (telegram_id,)
    ).fetchone()
    user = conn.execute(
        "SELECT steam_id, avatar_url, persona_name FROM users WHERE chat_id=?", (telegram_id,)
    ).fetchone()
    trade_count = conn.execute(
        "SELECT COUNT(*) as c FROM trades WHERE owner_id=? AND status='closed'", (telegram_id,)
    ).fetchone()["c"]
    conn.close()
    return jsonify({
        "ok":                True,
        "telegram_id":       telegram_id,
        "display_name":      acc["display_name"]      if acc else "",
        "first_name":        acc["first_name"]         if acc else "",
        "username":          acc["username"]            if acc else "",
        "steam_id":          user["steam_id"]           if user else None,
        "avatar_url":        user["avatar_url"]         if user else "",
        "persona_name":      user["persona_name"]       if user else "",
        "trade_link":        (acc["trade_link"] if acc["trade_link_public"] else "") if acc else "",
        "trade_link_public": acc["trade_link_public"]   if acc else 0,
        "successful_trades": trade_count,
        "verified":          acc["verified"]             if acc else 0,
    })

@app.route("/api/report", methods=["POST"])
@login_required
def api_report():
    tid     = session['telegram_id']
    data    = request.json or {}
    subject = data.get("subject", "").strip()[:128]
    message = data.get("message", "").strip()[:2000]
    if not subject or not message:
        return jsonify({"ok": False, "error": "Заполни тему и сообщение"}), 400

    now  = int(datetime.now().timestamp())
    conn = get_db()
    conn.execute(
        "INSERT INTO reports (reporter_id, subject, message, created_at) VALUES (?,?,?,?)",
        (tid, subject, message, now)
    )
    admin = conn.execute(
        "SELECT telegram_id FROM accounts WHERE role='admin' LIMIT 1"
    ).fetchone()
    if admin:
        acc  = conn.execute(
            "SELECT username, first_name FROM accounts WHERE telegram_id=?", (tid,)
        ).fetchone()
        name = esc_html(acc["first_name"] or acc["username"] or tid) if acc else tid
        tg_msg = (
            f"📣 <b>Новый репорт</b>\n\n"
            f"От: <code>{tid}</code> ({name})\n"
            f"Тема: <b>{esc_html(subject)}</b>\n\n"
            f"{esc_html(message)}"
        )
        conn.execute(
            "INSERT INTO pending_tg_notifications (chat_id, message, sent, created_at) VALUES (?,?,0,?)",
            (admin["telegram_id"], tg_msg, now)
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/reports")
@login_required
def api_reports_list():
    if session.get('role') != 'admin':
        return jsonify({"error": "Нет прав"}), 403
    conn = get_db()
    rows = conn.execute(
        "SELECT id, reporter_id, subject, message, created_at, is_read, "
        "COALESCE(status,'pending') AS status FROM reports ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/reports/<int:report_id>/reply", methods=["POST"])
@admin_required
def api_report_reply(report_id):
    data    = request.json or {}
    message = data.get("message", "").strip()[:2000]
    conn    = get_db()
    rep     = conn.execute(
        "SELECT reporter_id, subject FROM reports WHERE id=?", (report_id,)
    ).fetchone()
    if not rep:
        conn.close()
        return jsonify({"ok": False, "error": "Не найден"}), 404
    conn.execute("UPDATE reports SET is_read=1 WHERE id=?", (report_id,))
    if message:
        pref = conn.execute(
            "SELECT COALESCE(notif_reports,1) AS nr FROM accounts WHERE telegram_id=?",
            (rep["reporter_id"],)
        ).fetchone()
        if not pref or pref["nr"]:
            admin_acc = conn.execute(
                "SELECT first_name, username FROM accounts WHERE telegram_id=?",
                (session["telegram_id"],)
            ).fetchone()
            admin_name = (admin_acc["first_name"] or admin_acc["username"] or "Администратор") if admin_acc else "Администратор"
            tg_msg = (
                f"📬 <b>Ответ на ваш репорт</b>\n\n"
                f"Тема: <b>{esc_html(rep['subject'])}</b>\n\n"
                f"<b>{esc_html(admin_name)}:</b> {esc_html(message)}"
            )
            conn.execute(
                "INSERT INTO pending_tg_notifications (chat_id, message, sent, created_at) VALUES (?,?,0,?)",
                (rep["reporter_id"], tg_msg, int(datetime.now().timestamp()))
            )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/reports/<int:report_id>/close", methods=["POST"])
@admin_required
def api_report_close(report_id):
    data    = request.json or {}
    message = data.get("message", "").strip()[:2000]
    conn    = get_db()
    rep     = conn.execute(
        "SELECT reporter_id, subject FROM reports WHERE id=?", (report_id,)
    ).fetchone()
    if not rep:
        conn.close()
        return jsonify({"ok": False, "error": "Не найден"}), 404
    conn.execute("UPDATE reports SET is_read=1, status='closed' WHERE id=?", (report_id,))
    if message:
        pref = conn.execute(
            "SELECT COALESCE(notif_reports,1) AS nr FROM accounts WHERE telegram_id=?",
            (rep["reporter_id"],)
        ).fetchone()
        if not pref or pref["nr"]:
            admin_acc = conn.execute(
                "SELECT first_name, username FROM accounts WHERE telegram_id=?",
                (session["telegram_id"],)
            ).fetchone()
            admin_name = (admin_acc["first_name"] or admin_acc["username"] or "Администратор") if admin_acc else "Администратор"
            tg_msg = (
                f"✅ <b>Ваш репорт закрыт</b>\n\n"
                f"Тема: <b>{esc_html(rep['subject'])}</b>\n\n"
                f"<b>{esc_html(admin_name)}:</b> {esc_html(message)}"
            )
            conn.execute(
                "INSERT INTO pending_tg_notifications (chat_id, message, sent, created_at) VALUES (?,?,0,?)",
                (rep["reporter_id"], tg_msg, int(datetime.now().timestamp()))
            )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# --- Stats / Config ---

@app.route("/api/stats")
@login_required
def api_stats():
    conn = get_db()
    total_prices = conn.execute("SELECT COUNT(*) as c FROM prices").fetchone()["c"]
    total_users  = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    total_items  = conn.execute("SELECT COUNT(*) as c FROM watchlist").fetchone()["c"]
    user_items   = conn.execute("SELECT COUNT(*) as c FROM user_items").fetchone()["c"]
    oldest = conn.execute("SELECT MIN(timestamp) as t FROM prices").fetchone()["t"]
    conn.close()
    age_days = 0
    if oldest:
        age_days = (datetime.now() - datetime.fromtimestamp(oldest)).days
    return jsonify({
        "total_prices": total_prices,
        "total_users":  total_users,
        "total_items":  total_items,
        "user_items":   user_items,
        "db_age_days":  age_days,
        "uptime":       age_days
    })

@app.route("/api/config")
@admin_required
def api_config():
    return jsonify({
        "check_interval": int(get_config("CHECK_INTERVAL", 300)),
        "spike_1h":       float(get_config("SPIKE_THRESHOLD_1H", 15)),
        "spike_24h":      float(get_config("SPIKE_THRESHOLD_24H", 30)),
        "drop_1h":        float(get_config("DROP_THRESHOLD_1H", -10)),
        "drop_24h":       float(get_config("DROP_THRESHOLD_24H", -20)),
        "min_volume":     int(get_config("MIN_VOLUME", 5)),
        "currency":       int(get_config("CURRENCY", 1)),
    })

@app.route("/api/config", methods=["POST"])
@admin_required
def api_config_save():
    data = request.json
    mapping = {
        "check_interval": "CHECK_INTERVAL",
        "spike_1h":       "SPIKE_THRESHOLD_1H",
        "spike_24h":      "SPIKE_THRESHOLD_24H",
        "drop_1h":        "DROP_THRESHOLD_1H",
        "drop_24h":       "DROP_THRESHOLD_24H",
        "min_volume":     "MIN_VOLUME",
        "currency":       "CURRENCY",
    }
    for k, db_key in mapping.items():
        if k in data:
            set_config(db_key, data[k])
    return jsonify({"ok": True})

# --- Watchlist ---

@app.route("/api/watchlist")
@login_required
def api_watchlist():
    telegram_id = session['telegram_id']
    conn = get_db()
    rows = conn.execute("""
        SELECT w.name, w.appid, w.added_at,
               COALESCE(NULLIF(w.rarity,''), ir.rarity, '')             as rarity,
               COALESCE(NULLIF(w.rarity_color,''), ir.rarity_color, '') as rarity_color,
               COALESCE(ir.item_type, '')                               as item_type
        FROM watchlist w
        LEFT JOIN item_rarity ir ON ir.name = w.name
        WHERE w.chat_id = ?
        ORDER BY w.added_at DESC
    """, (telegram_id,)).fetchall()
    result = []
    for r in rows:
        price_row = conn.execute(
            """SELECT price, volume, timestamp FROM prices
               WHERE item=? ORDER BY timestamp DESC LIMIT 1""",
            (r["name"],)
        ).fetchone()
        cutoff = int(datetime.now().timestamp()) - 3600
        old_row = conn.execute(
            """SELECT price FROM prices
               WHERE item=? AND timestamp <= ?
               ORDER BY timestamp DESC LIMIT 1""",
            (r["name"], cutoff)
        ).fetchone()
        price  = price_row["price"]     if price_row else None
        volume = price_row["volume"]    if price_row else None
        ts     = price_row["timestamp"] if price_row else None
        old_p  = old_row["price"]       if old_row   else None
        pct_1h = round(((price - old_p) / old_p) * 100, 1) if price and old_p else None
        result.append({
            "name":         r["name"],
            "appid":        r["appid"],
            "added_at":     r["added_at"],
            "price":        price,
            "volume":       volume,
            "last_seen":    ts,
            "pct_1h":       pct_1h,
            "rarity":       r["rarity"]       or "",
            "rarity_color": r["rarity_color"] or "",
            "item_type":    r["item_type"]    or "",
        })
    conn.close()
    return jsonify(result)

@app.route("/api/watchlist", methods=["POST"])
@login_required
def api_watchlist_add():
    telegram_id  = session['telegram_id']
    data         = request.json
    name         = data.get("name", "").strip()
    appid        = int(data.get("appid", 730))
    rarity       = data.get("rarity", "")       or ""
    rarity_color = data.get("rarity_color", "") or ""
    if not name:
        return jsonify({"ok": False, "error": "Пустое название"}), 400
    conn = get_db()
    if conn.execute("SELECT name FROM watchlist WHERE chat_id=? AND name=?", (telegram_id, name)).fetchone():
        conn.close()
        return jsonify({"ok": False, "error": "Уже в списке"}), 400
    conn.execute(
        "INSERT INTO watchlist (chat_id, name, appid, added_at, rarity, rarity_color) VALUES (?,?,?,?,?,?)",
        (telegram_id, name, appid, int(datetime.now().timestamp()), rarity, rarity_color)
    )
    conn.commit()
    # Кэшируем иконку сразу при добавлении, используя общее соединение
    _get_or_fetch_icon(name, appid, conn)
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/watchlist/<path:name>", methods=["DELETE"])
@login_required
def api_watchlist_delete(name):
    telegram_id = session['telegram_id']
    conn = get_db()
    conn.execute("DELETE FROM watchlist WHERE chat_id=? AND name=?", (telegram_id, name))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# --- Users ---

@app.route("/api/users")
@admin_required
def api_users():
    conn = get_db()
    rows = conn.execute("""
        SELECT
            a.telegram_id                  AS chat_id,
            a.role,
            a.created_at,
            COALESCE(a.username,      '') AS username,
            COALESCE(a.first_name,    '') AS first_name,
            COALESCE(a.display_name,  '') AS display_name,
            COALESCE(a.verified, 0)       AS verified,
            COALESCE(a.banned,   0)       AS banned,
            u.steam_url,
            u.steam_id,
            COALESCE(u.avatar_url,    '') AS avatar_url,
            (SELECT COUNT(*) FROM user_items  ui WHERE ui.chat_id  = a.telegram_id) AS items,
            (SELECT COUNT(*) FROM watchlist    w  WHERE w.chat_id   = a.telegram_id) AS watchlist_count
        FROM accounts a
        LEFT JOIN users u ON u.chat_id = a.telegram_id
        ORDER BY a.created_at DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/users/<chat_id>/items")
@login_required
def api_user_items(chat_id):
    if session.get('role') != 'admin' and session.get('telegram_id') != chat_id:
        return jsonify({"error": "Нет прав"}), 403
    conn = get_db()
    rows = conn.execute(
        "SELECT item_name, appid FROM user_items WHERE chat_id=? ORDER BY item_name",
        (chat_id,)
    ).fetchall()
    conn.close()
    return jsonify([{"name": r["item_name"], "appid": r["appid"]} for r in rows])

@app.route("/api/users/<chat_id>", methods=["DELETE"])
@admin_required
def api_user_delete(chat_id):
    conn = get_db()
    conn.execute("DELETE FROM users      WHERE chat_id=?",     (chat_id,))
    conn.execute("DELETE FROM user_items WHERE chat_id=?",     (chat_id,))
    conn.execute("DELETE FROM watchlist  WHERE chat_id=?",     (chat_id,))
    conn.execute("DELETE FROM accounts   WHERE telegram_id=?", (chat_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/users/<chat_id>/role", methods=["POST"])
@admin_required
def api_user_set_role(chat_id):
    role = (request.json or {}).get("role", "")
    if role not in ("admin", "moderator", "user"):
        return jsonify({"ok": False, "error": "Неверная роль"}), 400
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO accounts (telegram_id, role, created_at, username, first_name) "
        "VALUES (?,?,?,?,?)",
        (chat_id, role, int(datetime.now().timestamp()), '', '')
    )
    conn.execute("UPDATE accounts SET role=? WHERE telegram_id=?", (role, chat_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/admin/users/<chat_id>")
@admin_required
def api_admin_user_detail(chat_id):
    conn = get_db()
    row = conn.execute("""
        SELECT
            a.telegram_id AS chat_id,
            a.role,
            a.created_at,
            COALESCE(a.username,      '') AS username,
            COALESCE(a.first_name,    '') AS first_name,
            COALESCE(a.display_name,  '') AS display_name,
            COALESCE(a.trade_link,    '') AS trade_link,
            COALESCE(a.verified, 0)       AS verified,
            COALESCE(a.banned,   0)       AS banned,
            u.steam_url,
            u.steam_id,
            COALESCE(u.avatar_url,    '') AS avatar_url,
            COALESCE(u.persona_name,  '') AS persona_name,
            (SELECT COUNT(*) FROM user_items ui WHERE ui.chat_id = a.telegram_id) AS items,
            (SELECT COUNT(*) FROM watchlist  w  WHERE w.chat_id  = a.telegram_id) AS watchlist_count
        FROM accounts a
        LEFT JOIN users u ON u.chat_id = a.telegram_id
        WHERE a.telegram_id = ?
    """, (chat_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Не найден"}), 404
    reports_about = conn.execute(
        "SELECT id, reporter_id, subject, message, created_at, is_read, "
        "COALESCE(status,'pending') AS status FROM reports "
        "WHERE subject LIKE ? OR message LIKE ? ORDER BY created_at DESC LIMIT 20",
        (f'%{chat_id}%', f'%{chat_id}%')
    ).fetchall()
    reports_by = conn.execute(
        "SELECT id, reporter_id, subject, message, created_at, is_read, "
        "COALESCE(status,'pending') AS status FROM reports "
        "WHERE reporter_id=? ORDER BY created_at DESC LIMIT 20",
        (chat_id,)
    ).fetchall()
    conn.close()
    return jsonify({
        **dict(row),
        "reports_about": [dict(r) for r in reports_about],
        "reports_by":    [dict(r) for r in reports_by],
    })


@app.route("/api/admin/users/<chat_id>/verify", methods=["POST"])
@admin_required
def api_admin_user_verify(chat_id):
    conn = get_db()
    row = conn.execute("SELECT verified FROM accounts WHERE telegram_id=?", (chat_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "Не найден"}), 404
    new_val = 0 if row["verified"] else 1
    conn.execute("UPDATE accounts SET verified=? WHERE telegram_id=?", (new_val, chat_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "verified": new_val})


@app.route("/api/admin/users/<chat_id>/display-name", methods=["POST"])
@admin_required
def api_admin_user_display_name(chat_id):
    name = (request.json or {}).get("display_name", "").strip()[:64]
    conn = get_db()
    conn.execute("UPDATE accounts SET display_name=? WHERE telegram_id=?", (name, chat_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/users/<chat_id>/unlink-steam", methods=["POST"])
@admin_required
def api_admin_user_unlink_steam(chat_id):
    conn = get_db()
    conn.execute("DELETE FROM users WHERE chat_id=?", (chat_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/users/<chat_id>/ban", methods=["POST"])
@admin_required
def api_admin_user_ban(chat_id):
    conn = get_db()
    row = conn.execute("SELECT banned FROM accounts WHERE telegram_id=?", (chat_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "Не найден"}), 404
    new_val = 0 if row["banned"] else 1
    conn.execute("UPDATE accounts SET banned=? WHERE telegram_id=?", (new_val, chat_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "banned": new_val})


# --- Prices ---

@app.route("/api/prices/<path:item_name>")
@login_required
def api_prices(item_name):
    conn = get_db()
    days = request.args.get("days", 30, type=int)
    if days > 0:
        cutoff = int((datetime.now() - timedelta(days=days)).timestamp())
        rows = conn.execute(
            """SELECT price, volume, timestamp, currency FROM prices
               WHERE item=? AND timestamp >= ?
               ORDER BY timestamp ASC""",
            (item_name, cutoff)
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT price, volume, timestamp, currency FROM prices
               WHERE item=? ORDER BY timestamp ASC""",
            (item_name,)
        ).fetchall()
    conn.close()
    return jsonify([{
        "price":    r["price"],
        "volume":   r["volume"],
        "ts":       r["timestamp"],
        "currency": r["currency"],
    } for r in rows])

@app.route("/api/db/purge", methods=["POST"])
@admin_required
def api_purge():
    days = int(request.json.get("days", 35))
    cutoff = int((datetime.now() - timedelta(days=days)).timestamp())
    conn = get_db()
    result = conn.execute("DELETE FROM prices WHERE timestamp < ?", (cutoff,))
    conn.commit()
    deleted = result.rowcount
    conn.close()
    return jsonify({"ok": True, "deleted": deleted})

# --- Steam helpers ---

@app.route("/api/steam/parse-url", methods=["POST"])
@login_required
def api_parse_url():
    raw = request.json.get("url", "").strip()
    if not raw:
        return jsonify({"ok": False, "error": "Пустая строка"}), 400
    if not raw.startswith("http"):
        raw = "https://" + raw
    m = re.search(r'market/listings/(\d+)/(.+)', raw)
    if not m:
        return jsonify({"ok": False, "error": "Не похоже на ссылку Steam Marketplace.\nПример: steamcommunity.com/market/listings/730/AK-47%20%7C%20Redline"}), 400
    appid = int(m.group(1))
    name  = urllib.parse.unquote(m.group(2).split("?")[0])
    if not name:
        return jsonify({"ok": False, "error": "Не удалось извлечь название предмета"}), 400
    return jsonify({"ok": True, "name": name, "appid": appid})

@app.route("/api/steam/image/<path:icon_hash>")
def api_steam_image(icon_hash):
    safe_name = icon_hash.replace("/", "_").replace("..", "")
    local_path = os.path.join(SKIN_IMG_DIR, safe_name + ".png")
    if os.path.exists(local_path):
        return send_file(local_path, mimetype="image/png")
    try:
        url = f"https://community.cloudflare.steamstatic.com/economy/image/{icon_hash}/360fx360f"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data  = resp.read()
            ctype = resp.headers.get("Content-Type", "image/png")
        with open(local_path, "wb") as f:
            f.write(data)
        return Response(data, content_type=ctype)
    except Exception:
        return Response(status=404)

@app.route("/api/steam/import-history/<path:item_name>", methods=["POST"])
@login_required
def api_import_history(item_name):
    conn = get_db()
    if conn.execute("SELECT 1 FROM history_imported WHERE item=?", (item_name,)).fetchone():
        conn.close()
        return jsonify({"ok": True, "skipped": True})

    appid = request.json.get("appid", 730)
    try:
        encoded = urllib.parse.quote(item_name)
        url = f"https://steamcommunity.com/market/listings/{appid}/{encoded}"
        req = urllib.request.Request(url, headers={
            "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        idx = html.find("var line1=")
        if idx == -1:
            conn.close()
            return jsonify({"ok": False, "error": "line1 не найден на странице Steam"})

        start = idx + len("var line1=")
        depth = 0
        end   = start
        for i, c in enumerate(html[start:]):
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    end = start + i + 1
                    break

        price_data = json.loads(html[start:end])
        MONTHS = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
                  "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
        inserted = 0
        for entry in price_data:
            try:
                date_str = entry[0]
                price    = float(entry[1])
                if price <= 0:
                    continue
                m = re.match(r"(\w{3})\s+(\d+)\s+(\d{4})\s+(\d+)", date_str)
                if not m:
                    continue
                month = MONTHS.get(m.group(1))
                if not month:
                    continue
                ts = int(datetime(int(m.group(3)), month, int(m.group(2)), int(m.group(4))).timestamp())
                conn.execute(
                    "INSERT OR IGNORE INTO prices VALUES (?,?,?,?,?)",
                    (item_name, price, 0, 1, ts)
                )
                inserted += 1
            except Exception:
                continue

        conn.execute(
            "INSERT OR REPLACE INTO history_imported VALUES (?,?)",
            (item_name, int(datetime.now().timestamp()))
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "skipped": False, "inserted": inserted})

    except Exception as e:
        conn.close()
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/steam/item-info/<path:item_name>")
@login_required
def api_item_info(item_name):
    appid = request.args.get("appid", 730)
    icon  = _get_or_fetch_icon(item_name, appid)
    if icon:
        return jsonify({"ok": True, "icon_url": icon})
    return jsonify({"ok": False})

@app.route("/api/steam/search")
@login_required
def api_steam_search():
    query = request.args.get("q", "").strip()
    appid = request.args.get("appid", "730")
    if len(query) < 2:
        return jsonify([])
    try:
        params = urllib.parse.urlencode({
            "query": query, "start": 0, "count": 10,
            "search_descriptions": 0, "sort_column": "popular",
            "sort_dir": "desc", "appid": appid, "norender": 1,
        })
        url = f"https://steamcommunity.com/market/search/render/?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        results = []
        for item in data.get("results", []):
            name  = item.get("name") or item.get("hash_name", "")
            asset = item.get("asset_description", {})
            rarity = rarity_color = ""
            for tag in asset.get("tags", []):
                if tag.get("category") == "Rarity":
                    rarity       = tag.get("internal_name", "")
                    rarity_color = tag.get("color", "")
                    break
            results.append({
                "name":         name,
                "appid":        asset.get("appid", int(appid)),
                "icon":         asset.get("icon_url", ""),
                "rarity":       rarity,
                "rarity_color": rarity_color,
            })
        return jsonify(results)
    except Exception:
        return jsonify([])


# --- cs2.sh price API ---

CS2SH_API_BASE = "https://api.cs2.sh"

_CS2SH_SITES = [
    ("buff",     "BUFF",     "#f5a623", "https://buff.163.com/market/goods?keyword={}"),
    ("youpin",   "Youpin",   "#ff6b35", "https://www.youpin898.com/"),
    ("csfloat",  "CSFloat",  "#00d4aa", "https://csfloat.com/"),
    ("steam",    "Steam",    "#1b2838", "https://steamcommunity.com/market/listings/730/{}"),
    ("skinport", "Skinport", "#1a9fff", "https://skinport.com/market?search={}"),
    ("c5game",   "C5Game",   "#26de81", "https://www.c5game.com/"),
]

_cs2sh_cache: dict = {}  # {item_name: {"ts": float, "data": dict}}


def _cs2sh_fetch_prices(item_name: str) -> dict | None:
    """POST /v1/prices/latest for a single item. Returns raw marketplace dict or None."""
    api_key = get_config("CS2SH_API_KEY", "")
    if not api_key:
        return None
    try:
        body = json.dumps({"market_hash_names": [item_name]}).encode()
        req  = urllib.request.Request(
            f"{CS2SH_API_BASE}/v1/prices/latest",
            data=body,
            headers={
                "Authorization":   f"Bearer {api_key}",
                "Content-Type":    "application/json",
                "Accept-Encoding": "gzip",
                "User-Agent":      "cs2-dashboard/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
        data = json.loads(raw)
        return data.get(item_name)
    except urllib.error.HTTPError as e:
        print(f"[cs2sh] HTTP {e.code} for {item_name}")
    except Exception as e:
        print(f"[cs2sh] {item_name}: {e}")
    return None


@app.route("/api/item-sites/<path:item_name>")
@login_required
def api_item_sites(item_name):
    cached = _cs2sh_cache.get(item_name)
    if cached and (datetime.now().timestamp() - cached["ts"]) < 300:
        return jsonify(cached["data"])

    enc        = urllib.parse.quote(item_name)
    mkt        = _cs2sh_fetch_prices(item_name) or {}
    steam_data = mkt.get("steam") or {}
    steam_usd  = steam_data.get("ask")

    sites = []
    for sid, name, color, url_tpl in _CS2SH_SITES:
        d   = mkt.get(sid) or {}
        url = url_tpl.format(enc) if "{}" in url_tpl else url_tpl
        sites.append({
            "id":   sid,
            "name": name,
            "color": color,
            "buy":  d.get("ask"),
            "sell": d.get("bid"),
            "url":  url,
        })

    api_key = get_config("CS2SH_API_KEY", "")
    data = {
        "steam_usd":     steam_usd,
        "sites":         sites,
        "no_api_key":    not bool(api_key),
    }
    _cs2sh_cache[item_name] = {"ts": datetime.now().timestamp(), "data": data}
    return jsonify(data)


@app.route("/api/config/cs2sh-key", methods=["POST"])
@admin_required
def api_set_cs2sh_key():
    key = (request.json or {}).get("key", "").strip()
    if not key:
        return jsonify({"ok": False, "error": "Пустой ключ"}), 400
    set_config("CS2SH_API_KEY", key)
    _cs2sh_cache.clear()
    return jsonify({"ok": True})


# --- Trades helpers ---

_WEAR_LABELS = {
    "Factory New": "FN", "Minimal Wear": "MW",
    "Field-Tested": "FT", "Well-Worn": "WW", "Battle-Scarred": "BS",
}

def _extract_wear(name):
    m = re.search(r'\(([^)]+)\)$', name)
    if m:
        return _WEAR_LABELS.get(m.group(1), m.group(1))
    return None

def _item_icon(conn, name):
    row = conn.execute("SELECT icon_url FROM item_rarity WHERE name=?", (name,)).fetchone()
    return row["icon_url"] if row and row["icon_url"] else ""

def _enrich_items(conn, rows):
    result = []
    for r in rows:
        name = r["item_name"]
        ir = conn.execute("SELECT icon_url, item_type FROM item_rarity WHERE name=?", (name,)).fetchone()
        result.append({
            "name":      name,
            "appid":     r["appid"],
            "icon":      ir["icon_url"] if ir and ir["icon_url"] else "",
            "wear":      _extract_wear(name),
            "item_type": ir["item_type"] if ir and ir["item_type"] else "",
        })
    return result


# --- Items search (autocomplete for trades wants) ---

@app.route("/api/items/search")
@login_required
def api_items_search():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    conn = get_db()
    rows = conn.execute("""
        SELECT name, icon_url FROM item_rarity
        WHERE name LIKE ? LIMIT 18
    """, (f"%{q}%",)).fetchall()
    conn.close()
    return jsonify([{
        "name": r["name"],
        "wear": _extract_wear(r["name"]),
        "icon": r["icon_url"] or "",
    } for r in rows])


# --- Trades API ---

@app.route("/api/trades")
@login_required
def api_trades_list():
    me  = session['telegram_id']
    tab = request.args.get("tab", "all")
    conn = get_db()

    if tab == "active_mine":
        rows = conn.execute("""
            SELECT id, owner_id, status, note, created_at FROM trades
            WHERE owner_id=? AND status='open' ORDER BY created_at DESC
        """, (me,)).fetchall()
    elif tab == "mine":
        rows = conn.execute("""
            SELECT id, owner_id, status, note, created_at FROM trades
            WHERE owner_id=? AND status!='open' ORDER BY created_at DESC
        """, (me,)).fetchall()
    elif tab == "my_offers":
        rows = conn.execute("""
            SELECT DISTINCT t.id, t.owner_id, t.status, t.note, t.created_at
            FROM trades t JOIN trade_offers o ON o.trade_id=t.id
            WHERE o.offerer_id=? ORDER BY t.created_at DESC
        """, (me,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT id, owner_id, status, note, created_at FROM trades
            WHERE status='open' ORDER BY created_at DESC
        """).fetchall()

    result = []
    for t in rows:
        items = conn.execute(
            "SELECT item_name, appid FROM trade_items WHERE trade_id=?", (t["id"],)
        ).fetchall()
        wants = conn.execute(
            "SELECT item_name, appid FROM trade_wants WHERE trade_id=?", (t["id"],)
        ).fetchall()
        offer_count = conn.execute(
            "SELECT COUNT(*) as c FROM trade_offers WHERE trade_id=? AND status='pending'",
            (t["id"],)
        ).fetchone()["c"]
        result.append({
            "id":           t["id"],
            "trade_number": f"#{str(t['id']).zfill(4)}",
            "owner_id":     t["owner_id"],
            "status":       t["status"],
            "note":         t["note"] or "",
            "created_at":   t["created_at"],
            "is_mine":      t["owner_id"] == me,
            "items":        _enrich_items(conn, items),
            "wants":        _enrich_items(conn, wants),
            "wants_any":    len(wants) == 0,
            "offer_count":  offer_count,
        })
    conn.close()
    return jsonify(result)


@app.route("/api/trades", methods=["POST"])
@login_required
def api_trade_create():
    me    = session['telegram_id']
    data  = request.json
    items = data.get("items", [])
    wants = data.get("wants", [])
    note  = data.get("note", "").strip()

    if not items:
        return jsonify({"ok": False, "error": "Выберите хотя бы один предмет"}), 400
    if len(items) > 5:
        return jsonify({"ok": False, "error": "Максимум 5 предметов в одном трейде"}), 400

    conn = get_db()
    user_inv = {r["item_name"] for r in conn.execute(
        "SELECT item_name FROM user_items WHERE chat_id=?", (me,)
    ).fetchall()}
    for name in items:
        if name not in user_inv:
            conn.close()
            return jsonify({"ok": False, "error": f"«{name}» не в вашем инвентаре"}), 400

    now = int(datetime.now().timestamp())
    cur = conn.execute(
        "INSERT INTO trades (owner_id, status, note, created_at) VALUES (?,?,?,?)",
        (me, "open", note, now)
    )
    trade_id = cur.lastrowid
    for name in items:
        conn.execute("INSERT INTO trade_items (trade_id, item_name) VALUES (?,?)", (trade_id, name))
    for name in wants:
        if name:
            conn.execute("INSERT INTO trade_wants (trade_id, item_name) VALUES (?,?)", (trade_id, name))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": trade_id})


@app.route("/api/trades/<int:trade_id>", methods=["DELETE"])
@login_required
def api_trade_cancel(trade_id):
    me = session['telegram_id']
    conn = get_db()
    t = conn.execute("SELECT owner_id FROM trades WHERE id=?", (trade_id,)).fetchone()
    if not t or (t["owner_id"] != me and session.get("role") != "admin"):
        conn.close()
        return jsonify({"ok": False, "error": "Нет прав"}), 403
    conn.execute("UPDATE trades SET status='cancelled' WHERE id=?", (trade_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/trades/<int:trade_id>/offers")
@login_required
def api_trade_offers_list(trade_id):
    me = session['telegram_id']
    conn = get_db()
    t = conn.execute("SELECT owner_id FROM trades WHERE id=?", (trade_id,)).fetchone()
    if not t or t["owner_id"] != me:
        conn.close()
        return jsonify({"error": "Нет прав"}), 403
    offers = conn.execute(
        "SELECT id, offerer_id, status, note, created_at FROM trade_offers WHERE trade_id=? ORDER BY created_at DESC",
        (trade_id,)
    ).fetchall()
    result = []
    for o in offers:
        offer_items = conn.execute(
            "SELECT item_name, appid FROM trade_offer_items WHERE offer_id=?", (o["id"],)
        ).fetchall()
        offerer_acc = conn.execute(
            "SELECT trade_link FROM accounts WHERE telegram_id=?", (o["offerer_id"],)
        ).fetchone()
        result.append({
            "id":                 o["id"],
            "offerer_id":         o["offerer_id"],
            "status":             o["status"],
            "note":               o["note"] or "",
            "created_at":         o["created_at"],
            "items":              _enrich_items(conn, offer_items),
            "offerer_trade_link": offerer_acc["trade_link"] if offerer_acc else "",
        })
    conn.close()
    return jsonify(result)


@app.route("/api/trades/<int:trade_id>/offers", methods=["POST"])
@login_required
def api_trade_offer_create(trade_id):
    me    = session['telegram_id']
    data  = request.json
    items = data.get("items", [])
    note  = data.get("note", "").strip()

    if not items:
        return jsonify({"ok": False, "error": "Выберите хотя бы один предмет"}), 400
    if len(items) > 5:
        return jsonify({"ok": False, "error": "Максимум 5 предметов в предложении"}), 400

    conn = get_db()
    t = conn.execute("SELECT owner_id, status FROM trades WHERE id=?", (trade_id,)).fetchone()
    if not t:
        conn.close()
        return jsonify({"ok": False, "error": "Трейд не найден"}), 404
    if t["status"] != "open":
        conn.close()
        return jsonify({"ok": False, "error": "Трейд уже закрыт"}), 400
    if t["owner_id"] == me:
        conn.close()
        return jsonify({"ok": False, "error": "Нельзя предлагать на собственный трейд"}), 400
    my_acc = conn.execute("SELECT trade_link FROM accounts WHERE telegram_id=?", (me,)).fetchone()
    if not my_acc or not my_acc["trade_link"]:
        conn.close()
        return jsonify({"ok": False, "error": "trade_link_missing"})
    existing = conn.execute(
        "SELECT id FROM trade_offers WHERE trade_id=? AND offerer_id=? AND status='pending'",
        (trade_id, me)
    ).fetchone()
    if existing:
        conn.close()
        return jsonify({"ok": False, "error": "Вы уже сделали предложение на этот трейд"}), 400

    user_inv = {r["item_name"] for r in conn.execute(
        "SELECT item_name FROM user_items WHERE chat_id=?", (me,)
    ).fetchall()}
    for name in items:
        if name not in user_inv:
            conn.close()
            return jsonify({"ok": False, "error": f"«{name}» не в вашем инвентаре"}), 400

    now = int(datetime.now().timestamp())
    cur = conn.execute(
        "INSERT INTO trade_offers (trade_id, offerer_id, status, note, created_at) VALUES (?,?,?,?,?)",
        (trade_id, me, "pending", note, now)
    )
    offer_id = cur.lastrowid
    for name in items:
        conn.execute("INSERT INTO trade_offer_items (offer_id, item_name) VALUES (?,?)", (offer_id, name))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "offer_id": offer_id})


@app.route("/api/trades/<int:trade_id>/offers/<int:offer_id>/respond", methods=["POST"])
@login_required
def api_trade_offer_respond(trade_id, offer_id):
    me     = session['telegram_id']
    action = request.json.get("action")
    if action not in ("accept", "decline"):
        return jsonify({"ok": False, "error": "Неверное действие"}), 400
    conn = get_db()
    t = conn.execute("SELECT owner_id, status FROM trades WHERE id=?", (trade_id,)).fetchone()
    if not t or t["owner_id"] != me:
        conn.close()
        return jsonify({"ok": False, "error": "Нет прав"}), 403
    if t["status"] != "open":
        conn.close()
        return jsonify({"ok": False, "error": "Трейд уже закрыт"}), 400
    o = conn.execute(
        "SELECT id, offerer_id FROM trade_offers WHERE id=? AND trade_id=?", (offer_id, trade_id)
    ).fetchone()
    if not o:
        conn.close()
        return jsonify({"ok": False, "error": "Предложение не найдено"}), 404
    if action == "accept":
        # Validate trade links
        my_acc = conn.execute("SELECT trade_link FROM accounts WHERE telegram_id=?", (me,)).fetchone()
        offerer_acc = conn.execute("SELECT trade_link FROM accounts WHERE telegram_id=?", (o["offerer_id"],)).fetchone()
        if not my_acc or not my_acc["trade_link"]:
            conn.close()
            return jsonify({"ok": False, "error": "trade_link_missing_owner"})
        if not offerer_acc or not offerer_acc["trade_link"]:
            conn.close()
            return jsonify({"ok": False, "error": "trade_link_missing_offerer"})
        offerer_trade_link = offerer_acc["trade_link"]
        conn.execute("UPDATE trade_offers SET status='accepted' WHERE id=?", (offer_id,))
        conn.execute(
            "UPDATE trade_offers SET status='declined' WHERE trade_id=? AND id!=? AND status='pending'",
            (trade_id, offer_id)
        )
        conn.execute("UPDATE trades SET status='closed' WHERE id=?", (trade_id,))

        # Получаем данные об оффере для уведомления
        offer_row = conn.execute(
            "SELECT offerer_id FROM trade_offers WHERE id=?", (offer_id,)
        ).fetchone()
        trade_items = conn.execute(
            "SELECT item_name FROM trade_items WHERE trade_id=?", (trade_id,)
        ).fetchall()
        offer_items = conn.execute(
            "SELECT item_name FROM trade_offer_items WHERE offer_id=?", (offer_id,)
        ).fetchall()

        if offer_row:
            trade_num   = f"#{str(trade_id).zfill(4)}"
            t_items_txt = "\n".join(f"  • {r['item_name']}" for r in trade_items)  or "  —"
            o_items_txt = "\n".join(f"  • {r['item_name']}" for r in offer_items)  or "  —"
            msg = (
                f"✅ <b>Ваше предложение принято!</b>\n\n"
                f"Трейд <b>{trade_num}</b>\n\n"
                f"<b>Вы предлагали:</b>\n{o_items_txt}\n\n"
                f"<b>Вы получите:</b>\n{t_items_txt}\n\n"
                f"⚡ <b>Следующий шаг — выполнить обмен в Steam:</b>\n"
                f"1. Откройте <b>Steam → Входящие предложения обмена</b>\n"
                f"2. Примите входящий трейд от владельца\n\n"
                f"<a href=\"http://localhost:5000\">Открыть панель</a>"
            )
            conn.execute(
                "INSERT INTO pending_tg_notifications (chat_id, message, sent, created_at) VALUES (?,?,0,?)",
                (offer_row["offerer_id"], msg, int(datetime.now().timestamp()))
            )
    else:
        conn.execute("UPDATE trade_offers SET status='declined' WHERE id=?", (offer_id,))
        offerer_trade_link = None
    conn.commit()
    conn.close()
    if action == "accept":
        return jsonify({"ok": True, "offerer_trade_link": offerer_trade_link})
    return jsonify({"ok": True})


if __name__ == "__main__":
    init_db()
    setup_secret()
    print("Dashboard: http://localhost:5000")
    app.run(debug=False, port=5000)
