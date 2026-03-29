from flask import Flask, jsonify, request, send_from_directory, Response
import sqlite3
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

app = Flask(__name__)
DB_PATH = "prices.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history_imported (
            item TEXT PRIMARY KEY,
            imported_at INTEGER
        )
    """)
    conn.commit()
    conn.close()

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

# --- API routes ---

@app.route("/")
def index():
    return send_from_directory(".", "dashboard.html")

@app.route("/api/stats")
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
        "total_users": total_users,
        "total_items": total_items,
        "user_items": user_items,
        "db_age_days": age_days,
        "uptime": age_days
    })

@app.route("/api/config")
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

@app.route("/api/watchlist")
def api_watchlist():
    conn = get_db()
    rows = conn.execute(
        "SELECT name, appid, added_at FROM watchlist ORDER BY added_at DESC"
    ).fetchall()
    result = []
    for r in rows:
        # Последняя цена
        price_row = conn.execute(
            """SELECT price, volume, timestamp FROM prices
               WHERE item=? ORDER BY timestamp DESC LIMIT 1""",
            (r["name"],)
        ).fetchone()
        # Цена час назад
        cutoff = int(datetime.now().timestamp()) - 3600
        old_row = conn.execute(
            """SELECT price FROM prices
               WHERE item=? AND timestamp <= ?
               ORDER BY timestamp DESC LIMIT 1""",
            (r["name"], cutoff)
        ).fetchone()
        price   = price_row["price"]   if price_row else None
        volume  = price_row["volume"]  if price_row else None
        ts      = price_row["timestamp"] if price_row else None
        old_p   = old_row["price"] if old_row else None
        pct_1h  = round(((price - old_p) / old_p) * 100, 1) if price and old_p else None
        result.append({
            "name":     r["name"],
            "appid":    r["appid"],
            "added_at": r["added_at"],
            "price":    price,
            "volume":   volume,
            "last_seen": ts,
            "pct_1h":   pct_1h,
        })
    conn.close()
    return jsonify(result)

@app.route("/api/watchlist", methods=["POST"])
def api_watchlist_add():
    data = request.json
    name  = data.get("name", "").strip()
    appid = int(data.get("appid", 730))
    if not name:
        return jsonify({"ok": False, "error": "Пустое название"}), 400
    conn = get_db()
    existing = conn.execute("SELECT name FROM watchlist WHERE name=?", (name,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"ok": False, "error": "Уже в списке"}), 400
    conn.execute(
        "INSERT INTO watchlist VALUES (?,?,?)",
        (name, appid, int(datetime.now().timestamp()))
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/watchlist/<path:name>", methods=["DELETE"])
def api_watchlist_delete(name):
    conn = get_db()
    conn.execute("DELETE FROM watchlist WHERE name=?", (name,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/users")
def api_users():
    conn = get_db()
    users = conn.execute(
        "SELECT chat_id, steam_url, steam_id, added_at FROM users ORDER BY added_at DESC"
    ).fetchall()
    result = []
    for u in users:
        count = conn.execute(
            "SELECT COUNT(*) as c FROM user_items WHERE chat_id=?",
            (u["chat_id"],)
        ).fetchone()["c"]
        result.append({
            "chat_id":   u["chat_id"],
            "steam_url": u["steam_url"],
            "steam_id":  u["steam_id"],
            "added_at":  u["added_at"],
            "items":     count,
        })
    conn.close()
    return jsonify(result)

@app.route("/api/users/<chat_id>/items")
def api_user_items(chat_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT item_name, appid FROM user_items WHERE chat_id=? ORDER BY item_name",
        (chat_id,)
    ).fetchall()
    conn.close()
    return jsonify([{"name": r["item_name"], "appid": r["appid"]} for r in rows])

@app.route("/api/users/<chat_id>", methods=["DELETE"])
def api_user_delete(chat_id):
    conn = get_db()
    conn.execute("DELETE FROM users WHERE chat_id=?", (chat_id,))
    conn.execute("DELETE FROM user_items WHERE chat_id=?", (chat_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/prices/<path:item_name>")
def api_prices(item_name):
    conn = get_db()
    cutoff = int((datetime.now() - timedelta(days=30)).timestamp())
    rows = conn.execute(
        """SELECT price, volume, timestamp FROM prices
           WHERE item=? AND timestamp >= ?
           ORDER BY timestamp ASC""",
        (item_name, cutoff)
    ).fetchall()
    conn.close()
    return jsonify([{
        "price": r["price"],
        "volume": r["volume"],
        "ts": r["timestamp"]
    } for r in rows])

@app.route("/api/db/purge", methods=["POST"])
def api_purge():
    days = int(request.json.get("days", 35))
    cutoff = int((datetime.now() - timedelta(days=days)).timestamp())
    conn = get_db()
    result = conn.execute("DELETE FROM prices WHERE timestamp < ?", (cutoff,))
    conn.commit()
    deleted = result.rowcount
    conn.close()
    return jsonify({"ok": True, "deleted": deleted})

@app.route("/api/steam/parse-url", methods=["POST"])
def api_parse_url():
    """Парсит Steam URL и возвращает название предмета и appid"""
    raw = request.json.get("url", "").strip()
    if not raw:
        return jsonify({"ok": False, "error": "Пустая строка"}), 400

    # Добавляем схему если нет
    if not raw.startswith("http"):
        raw = "https://" + raw

    # Паттерн: steamcommunity.com/market/listings/{appid}/{name}
    m = re.search(r'market/listings/(\d+)/(.+)', raw)
    if not m:
        return jsonify({"ok": False, "error": "Не похоже на ссылку Steam Marketplace.\nПример: steamcommunity.com/market/listings/730/AK-47%20%7C%20Redline"}), 400

    appid = int(m.group(1))
    name_encoded = m.group(2).split("?")[0]  # убираем query params
    name = urllib.parse.unquote(name_encoded)

    if not name:
        return jsonify({"ok": False, "error": "Не удалось извлечь название предмета"}), 400

    return jsonify({"ok": True, "name": name, "appid": appid})

@app.route("/api/steam/image/<path:icon_hash>")
def api_steam_image(icon_hash):
    """Проксирует изображение скина со Steam CDN"""
    try:
        url = f"https://community.cloudflare.steamstatic.com/economy/image/{icon_hash}/360fx360f"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "image/png")
        return Response(data, content_type=ctype)
    except Exception:
        return Response(status=404)

@app.route("/api/steam/import-history/<path:item_name>", methods=["POST"])
def api_import_history(item_name):
    """Импортирует историю цен со страницы Steam Market — только один раз на предмет"""
    conn = get_db()
    if conn.execute("SELECT 1 FROM history_imported WHERE item=?", (item_name,)).fetchone():
        conn.close()
        return jsonify({"ok": True, "skipped": True})

    appid = request.json.get("appid", 730)
    try:
        encoded = urllib.parse.quote(item_name)
        url = f"https://steamcommunity.com/market/listings/{appid}/{encoded}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Извлекаем массив line1 из JS на странице
        idx = html.find("var line1=")
        if idx == -1:
            conn.close()
            return jsonify({"ok": False, "error": "line1 не найден на странице Steam"})

        start = idx + len("var line1=")
        depth = 0
        end = start
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
                date_str = entry[0]   # "Dec 09 2021 01: +0"
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
def api_item_info(item_name):
    """Получает icon_url предмета через Steam Market Search"""
    try:
        params = urllib.parse.urlencode({
            "query": item_name, "start": 0, "count": 5,
            "search_descriptions": 0, "appid": 730, "norender": 1,
        })
        url = f"https://steamcommunity.com/market/search/render/?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        for item in data.get("results", []):
            name = item.get("name") or item.get("hash_name", "")
            if name == item_name:
                icon = item.get("asset_description", {}).get("icon_url", "")
                if icon:
                    return jsonify({"ok": True, "icon_url": icon})
        results = data.get("results", [])
        if results:
            icon = results[0].get("asset_description", {}).get("icon_url", "")
            if icon:
                return jsonify({"ok": True, "icon_url": icon})
    except Exception:
        pass
    return jsonify({"ok": False})

@app.route("/api/steam/search")
def api_steam_search():
    """Поиск предметов через Steam Market Search API"""
    query = request.args.get("q", "").strip()
    appid = request.args.get("appid", "730")
    if len(query) < 2:
        return jsonify([])
    try:
        params = urllib.parse.urlencode({
            "query": query,
            "start": 0,
            "count": 10,
            "search_descriptions": 0,
            "sort_column": "popular",
            "sort_dir": "desc",
            "appid": appid,
            "norender": 1,
        })
        url = f"https://steamcommunity.com/market/search/render/?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        results = []
        for item in data.get("results", []):
            name = item.get("name") or item.get("hash_name", "")
            asset = item.get("asset_description", {})
            results.append({
                "name":  name,
                "appid": asset.get("appid", int(appid)),
                "icon":  asset.get("icon_url", ""),
            })
        return jsonify(results)
    except Exception as e:
        return jsonify([])

if __name__ == "__main__":
    init_db()
    print("Панель запущена: http://localhost:5000")
    app.run(debug=False, port=5000)
