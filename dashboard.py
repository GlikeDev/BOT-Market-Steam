from flask import Flask, jsonify, request, send_from_directory
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
