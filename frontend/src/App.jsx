import { useState, useEffect, useCallback } from "react";
import InventoryPage from "./InventoryPage";
import "./index.css";

// ─── RARITY_MAP — mirrors dashboard.py / dashboard.html ──────────────────────
const RARITY_MAP = {
  Rarity_Common_Weapon:    "consumer",
  Rarity_Uncommon_Weapon:  "industrial",
  Rarity_Rare_Weapon:      "milspec",
  Rarity_Mythical_Weapon:  "restricted",
  Rarity_Legendary_Weapon: "classified",
  Rarity_Ancient_Weapon:   "covert",
  Rarity_Ancient:          "contraband",
  Rarity_Contraband:       "contraband",
  RARITY_COMMON:           "consumer",
  RARITY_UNCOMMON:         "industrial",
  RARITY_RARE:             "milspec",
  RARITY_MYTHICAL:         "restricted",
  RARITY_LEGENDARY:        "classified",
  RARITY_ANCIENT:          "covert",
  RARITY_CONTRABAND:       "contraband",
};

function parseRarity(raw) {
  return RARITY_MAP[raw] ?? "consumer";
}

// Split "AK-47 | Redline (Field-Tested)" → { weapon, skin, wear }
function parseName(name = "") {
  const pipeIdx = name.indexOf(" | ");
  if (pipeIdx === -1) return { weapon: name, skin: "", wear: "" };
  const weapon = name.slice(0, pipeIdx);
  const rest   = name.slice(pipeIdx + 3);
  const parenIdx = rest.lastIndexOf(" (");
  const skin = parenIdx !== -1 ? rest.slice(0, parenIdx) : rest;
  const wear = parenIdx !== -1 ? rest.slice(parenIdx + 2, -1) : "";
  return { weapon, skin, wear };
}

function mapItem(item, idx) {
  const { weapon, skin, wear } = parseName(item.name);
  const isCase = item.item_type === "CSGO_Type_WeaponCase" || item.name?.endsWith(" Case");
  return {
    id:       item.id ?? idx,
    name:     item.name,
    weapon:   weapon || item.name,
    skin:     skin   || "",
    wear:     wear   || "",
    price:    item.price   ?? 0,
    rarity:   parseRarity(item.rarity),
    float:    item.float_value ? parseFloat(item.float_value).toFixed(4) : "—",
    volume:   item.volume != null ? String(item.volume) : "—",
    stattrak: !!(item.name?.includes("StatTrak")),
    pattern:  item.pattern_index ?? null,
    imageUrl: item.icon_url ? `/api/steam/image/${item.icon_url}` : null,
    pct1h:    item.pct_1h  ?? null,
    pct24h:   item.pct_24h ?? null,
    notify:   item.notify  !== 0,
    appid:    item.appid   ?? 730,
    isCase,
  };
}

// Trigger background rarity fetch if any items are missing rarity
async function maybeFetchRarities(rawItems) {
  const missing = rawItems.filter(i => !i.rarity && !i.item_type?.includes("Case")).length;
  if (!missing) return false;
  let remaining = 1;
  while (remaining > 0) {
    const r = await fetch("/api/profile/fetch-rarities", { method: "POST" })
      .then(res => res.json()).catch(() => ({ ok: false }));
    if (!r.ok) break;
    remaining = r.remaining ?? 0;
    if (r.updated === 0) break;
  }
  return true;
}

// ─── App ─────────────────────────────────────────────────────────────────────
export default function App({ embedded = false }) {
  const [items, setItems]   = useState(null); // null = loading
  const [error, setError]   = useState(null);

  const loadItems = useCallback(() => {
    fetch("/api/profile/items")
      .then(r => {
        if (r.status === 401) throw new Error("auth");
        if (!r.ok)            throw new Error("fetch");
        return r.json();
      })
      .then(async data => {
        const raw = Array.isArray(data) ? data : (data.items ?? []);
        const mapped = raw.map(mapItem);
        setItems(mapped);
        // Background rarity fetch — reload items if new rarities were fetched
        const updated = await maybeFetchRarities(raw);
        if (updated) {
          const r2 = await fetch("/api/profile/items").then(r => r.json()).catch(() => null);
          if (r2) {
            const raw2 = Array.isArray(r2) ? r2 : (r2.items ?? []);
            setItems(raw2.map(mapItem));
          }
        }
      })
      .catch(err => setError(err.message));
  }, []);

  useEffect(() => {
    loadItems();
  }, [loadItems]);

  // When embedded in dashboard, also listen for inv:loaded event
  // (dashboard's loadProfile() fires this on "Обновить" button)
  useEffect(() => {
    if (!embedded) return;
    const handler = (e) => {
      const raw = e.detail?.items ?? [];
      setItems(raw.map(mapItem));
      setError(null);
    };
    window.addEventListener("inv:loaded", handler);
    return () => window.removeEventListener("inv:loaded", handler);
  }, [embedded]);

  // Auth error → redirect to login
  if (error === "auth") {
    window.location.href = "/login";
    return null;
  }

  // Loading
  if (items === null) {
    return (
      <div className="flex min-h-[200px] items-center justify-center">
        <div className="text-center">
          <div className="mb-3 h-8 w-8 animate-spin rounded-full border-2 border-[#00E5FF] border-t-transparent mx-auto" />
          <p className="font-mono text-xs text-slate-500">Загрузка инвентаря...</p>
        </div>
      </div>
    );
  }

  // API error / empty → fallback to demo
  if (error || items.length === 0) {
    return <InventoryPage embedded={embedded} />;
  }

  return <InventoryPage initialItems={items} embedded={embedded} />;
}
