import { useState, useMemo, useCallback } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import { SkinCard, type SkinItem as Item } from "./SkinCard";
import { DetailModal } from "./DetailModal";

// ─── Filter data ──────────────────────────────────────────────────────────────
const PISTOLS = new Set(["Glock-18","USP-S","Desert Eagle","P250","Five-SeveN","Tec-9","CZ75-Auto","Dual Berettas","P2000","R8 Revolver"]);
const SNIPERS = new Set(["AWP","SSG 09","SCAR-20","G3SG1"]);
const RIFLES  = new Set(["AK-47","M4A4","M4A1-S","SG 553","AUG","FAMAS","Galil AR"]);
const SMG     = new Set(["MP9","MP5-SD","MAC-10","PP-Bizon","P90","UMP-45","MP7"]);
const HEAVY   = new Set(["Nova","XM1014","Sawed-Off","MAG-7","M249","Negev"]);

function getType(item: Item): string {
  if (item.weapon.startsWith("★"))   return "knife";
  if (SNIPERS.has(item.weapon))      return "sniper";
  if (RIFLES.has(item.weapon))       return "rifle";
  if (PISTOLS.has(item.weapon))      return "pistol";
  if (SMG.has(item.weapon))          return "smg";
  if (HEAVY.has(item.weapon))        return "heavy";
  return "other";
}

const TYPE_OPTIONS = [
  { value: "knife",  label: "Ножи"         },
  { value: "rifle",  label: "Винтовки"     },
  { value: "sniper", label: "Снайперские"  },
  { value: "pistol", label: "Пистолеты"   },
  { value: "smg",    label: "SMG"          },
  { value: "heavy",  label: "Тяжёлое"     },
  { value: "other",  label: "Прочее"       },
];

const WEAR_OPTIONS = [
  { value: "Factory New",   label: "Factory New"   },
  { value: "Minimal Wear",  label: "Minimal Wear"  },
  { value: "Field-Tested",  label: "Field-Tested"  },
  { value: "Well-Worn",     label: "Well-Worn"     },
  { value: "Battle-Scarred",label: "Battle-Scarred"},
];

const RARITY_OPTIONS = [
  { value: "consumer",   label: "Ширпотреб"      },
  { value: "industrial", label: "Промышленное"   },
  { value: "milspec",    label: "Армейское"      },
  { value: "restricted", label: "Запрещённое"   },
  { value: "classified", label: "Засекреченное" },
  { value: "covert",     label: "Тайное"         },
  { value: "contraband", label: "Контрабанда"   },
];

interface Filters { search: string; type: string; wear: string; rarity: string; }
const FILTERS_EMPTY: Filters = { search: "", type: "", wear: "", rarity: "" };

// ─── FilterSelect — glassmorphism dropdown ────────────────────────────────────
function FilterSelect({
  value, onChange, options, placeholder,
}: {
  value:       string;
  onChange:    (v: string) => void;
  options:     { value: string; label: string }[];
  placeholder: string;
}) {
  return (
    <div style={{ position: "relative", flexShrink: 0 }}>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="inv-filter-select"
      >
        <option value="">{placeholder}</option>
        {options.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
      {/* Custom chevron */}
      <svg
        width="10" height="6" viewBox="0 0 10 6" fill="none"
        style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", pointerEvents: "none", opacity: 0.5 }}
      >
        <path d="M1 1l4 4 4-4" stroke="#EDF0F7" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    </div>
  );
}

// ─── FilterBar ────────────────────────────────────────────────────────────────
function FilterBar({
  filters,
  onChange,
  totalVisible,
  totalAll,
}: {
  filters:      Filters;
  onChange:     (f: Filters) => void;
  totalVisible: number;
  totalAll:     number;
}) {
  const isActive = filters.search || filters.type || filters.wear || filters.rarity;

  return (
    <motion.div
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      style={{
        display: "flex", alignItems: "center", gap: 8,
        flexWrap: "wrap", marginBottom: 14,
      }}
    >
      {/* Search input */}
      <div style={{ position: "relative", flex: "1 1 180px", minWidth: 140 }}>
        <svg width="13" height="13" viewBox="0 0 13 13" fill="none"
          style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", opacity: 0.38, pointerEvents: "none" }}
        >
          <circle cx="5.5" cy="5.5" r="4.5" stroke="#EDF0F7" strokeWidth="1.4"/>
          <path d="M9 9l2.5 2.5" stroke="#EDF0F7" strokeWidth="1.4" strokeLinecap="round"/>
        </svg>
        <input
          type="text"
          value={filters.search}
          onChange={e => onChange({ ...filters, search: e.target.value })}
          placeholder="Поиск по названию..."
          className="inv-filter-input"
          style={{ paddingLeft: 30 }}
        />
      </div>

      {/* Type dropdown */}
      <FilterSelect
        value={filters.type}
        onChange={v => onChange({ ...filters, type: v })}
        options={TYPE_OPTIONS}
        placeholder="Тип"
      />

      {/* Wear dropdown */}
      <FilterSelect
        value={filters.wear}
        onChange={v => onChange({ ...filters, wear: v })}
        options={WEAR_OPTIONS}
        placeholder="Качество"
      />

      {/* Rarity dropdown */}
      <FilterSelect
        value={filters.rarity}
        onChange={v => onChange({ ...filters, rarity: v })}
        options={RARITY_OPTIONS}
        placeholder="Редкость"
      />

      {/* Results count + reset */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
        {isActive && (
          <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, color: "rgba(255,255,255,0.35)" }}>
            {totalVisible} / {totalAll}
          </span>
        )}
        <AnimatePresence>
          {isActive && (
            <motion.button
              initial={{ opacity: 0, scale: 0.85 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.85 }}
              transition={{ duration: 0.15 }}
              onClick={() => onChange(FILTERS_EMPTY)}
              style={{
                padding: "4px 10px", borderRadius: 6, cursor: "pointer",
                border: "1px solid rgba(255,32,96,0.3)",
                background: "rgba(255,32,96,0.08)",
                color: "#FF2060", fontSize: 11,
                fontFamily: "'Rajdhani', sans-serif", fontWeight: 600,
                letterSpacing: "0.04em",
              }}
            >
              × Сбросить
            </motion.button>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

// ─── Design System: Elite Trader Dark ────────────────────────────────────────
//
//  Fonts
//    Headings / weapons : Rajdhani 600–700
//    Prices / data      : JetBrains Mono 400–700
//    Body               : Inter / system
//
//  Palette
//    bg-base   : #06080E          – deepest layer (set in index.css)
//    bg-glass  : rgba(13,17,32,.65) + backdrop-blur(20px)
//    border    : rgba(255,255,255,.08)
//    cyan      : #00E5FF  – primary accent
//    purple    : #B041FF  – secondary accent
//    amber     : #FFB300  – warm highlight
//    blue      : #4B69FF  – milspec / data accent
//    green     : #00FF94  – profit / up
//    red       : #FF2060  – loss / down
//    text      : #EDF0F7
//    muted     : rgba(255,255,255,.38)

// Glassmorphism token
const GLASS: React.CSSProperties = {
  background:           "rgba(13, 17, 32, 0.65)",
  backdropFilter:       "blur(20px)",
  WebkitBackdropFilter: "blur(20px)",
  border:               "1px solid rgba(255,255,255,0.08)",
  borderRadius:         16,
};

// Rarity palette – mirrors dashboard.html / SkinTransition
const RARITY: Record<string, { label: string; color: string }> = {
  consumer:   { label: "Ширпотреб",     color: "#A8A8A8" },
  industrial: { label: "Промышленное",  color: "#6496E1" },
  milspec:    { label: "Армейское",     color: "#4B69FF" },
  restricted: { label: "Запрещённое",   color: "#8847FF" },
  classified: { label: "Засекреченное", color: "#D32CE6" },
  covert:     { label: "Тайное",        color: "#EB4B4B" },
  contraband: { label: "Контрабанда",   color: "#E4AE39" },
};

const SPRING = { type: "spring" as const, stiffness: 380, damping: 36, mass: 0.8 };

// ─── Helpers ──────────────────────────────────────────────────────────────────
const fmtUSD = (v: number | null) =>
  v != null
    ? new Intl.NumberFormat("en-US", {
        style: "currency", currency: "USD", maximumFractionDigits: 2,
      }).format(v)
    : "—";

const fmtPct = (v: number | null) =>
  v != null ? `${v >= 0 ? "+" : ""}${v.toFixed(1)}%` : null;

// ─── PctChip ──────────────────────────────────────────────────────────────────
function PctChip({ value }: { value: number | null }) {
  const str = fmtPct(value);
  if (!str)
    return (
      <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, color: "rgba(255,255,255,0.22)" }}>
        —
      </span>
    );
  const up = value! >= 0;
  return (
    <span
      style={{
        fontFamily:   "JetBrains Mono, monospace",
        fontSize:     10,
        fontWeight:   700,
        padding:      "2px 6px",
        borderRadius: 99,
        color:        up ? "#00FF94" : "#FF2060",
        background:   up ? "rgba(0,255,148,0.12)" : "rgba(255,32,96,0.12)",
        border:       `1px solid ${up ? "rgba(0,255,148,0.25)" : "rgba(255,32,96,0.25)"}`,
        whiteSpace:   "nowrap",
      }}
    >
      {str}
    </span>
  );
}

// ─── StatCard ─────────────────────────────────────────────────────────────────
function StatCard({
  children,
  style,
  accentColor,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
  accentColor: string;
}) {
  return (
    <motion.div
      style={{ ...GLASS, ...style, position: "relative", padding: "16px 20px", overflow: "hidden" }}
      whileHover={{
        y: -5,
        boxShadow: `0 16px 48px ${accentColor}1A`,
        transition: { duration: 0.22, ease: [0.22, 1, 0.36, 1] },
      }}
    >
      {/* Accent top edge */}
      <div
        style={{
          position: "absolute", top: 0, left: 0, right: 0, height: 1,
          background: `linear-gradient(90deg, ${accentColor}, transparent 70%)`,
          opacity: 0.9,
        }}
      />
      {children}
    </motion.div>
  );
}

// ─── StatsGrid (Bento) ────────────────────────────────────────────────────────
function StatsGrid({ items }: { items: Item[] }) {
  const totalValue = useMemo(
    () => items.reduce((s, i) => s + (i.price || 0), 0),
    [items],
  );

  const withPct1h  = useMemo(() => items.filter(i => i.pct1h  != null), [items]);
  const withPct24h = useMemo(() => items.filter(i => i.pct24h != null), [items]);

  const avg1h  = withPct1h.length
    ? withPct1h.reduce((s, i)  => s + i.pct1h!,  0) / withPct1h.length
    : null;
  const avg24h = withPct24h.length
    ? withPct24h.reduce((s, i) => s + i.pct24h!, 0) / withPct24h.length
    : null;

  const profit1h  = avg1h  != null ? (totalValue * avg1h)  / 100 : null;
  const profit24h = avg24h != null ? (totalValue * avg24h) / 100 : null;

  const upCount      = withPct1h.filter(i => i.pct1h!  >  0.1).length;
  const downCount    = withPct1h.filter(i => i.pct1h!  < -0.1).length;
  const neutralCount = items.length - upCount - downCount;
  const total        = items.length || 1;

  const LBL: React.CSSProperties = {
    fontSize: 10, color: "rgba(255,255,255,0.38)",
    textTransform: "uppercase", letterSpacing: "0.11em",
    fontWeight: 600, marginBottom: 10,
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y:   0 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      style={{
        display: "grid",
        gridTemplateColumns: "2fr 1fr 1fr",
        gridTemplateRows: "auto auto",
        gap: 10,
        marginBottom: 20,
      }}
    >
      {/* ── Портфель (spans 2 cols) ── */}
      <StatCard style={{ gridColumn: "1 / 3", gridRow: 1 }} accentColor="#00E5FF">
        <div style={LBL}>Портфель</div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
          <span
            style={{
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 30, fontWeight: 700, color: "#EDF0F7", lineHeight: 1.1,
            }}
          >
            {fmtUSD(totalValue)}
          </span>
          {avg24h != null && <PctChip value={avg24h} />}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 10, color: "rgba(255,255,255,0.35)", textTransform: "uppercase", letterSpacing: "0.09em", fontWeight: 600 }}>
            За 24ч
          </span>
          {profit24h != null && (
            <span
              style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 13, fontWeight: 700,
                color: profit24h >= 0 ? "#00FF94" : "#FF2060",
              }}
            >
              {profit24h >= 0 ? "+" : ""}{fmtUSD(profit24h)}
            </span>
          )}
          {avg24h != null && (
            <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11, color: "rgba(255,255,255,0.4)" }}>
              {fmtPct(avg24h)}
            </span>
          )}
        </div>
      </StatCard>

      {/* ── Скинов ── */}
      <StatCard style={{ gridColumn: 3, gridRow: 1 }} accentColor="#FFB300">
        <div style={LBL}>Скинов</div>
        <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 26, fontWeight: 700, color: "#EDF0F7", lineHeight: 1.1 }}>
          {items.length}
        </div>
      </StatCard>

      {/* ── За 1ч ── */}
      <StatCard style={{ gridColumn: 1, gridRow: 2 }} accentColor="#B041FF">
        <div style={LBL}>За 1ч</div>
        <div
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 22, fontWeight: 700, lineHeight: 1.1,
            color: profit1h != null
              ? profit1h >= 0 ? "#00FF94" : "#FF2060"
              : "#EDF0F7",
          }}
        >
          {profit1h != null
            ? `${profit1h >= 0 ? "+" : ""}${fmtUSD(profit1h)}`
            : "—"}
        </div>
        {avg1h != null && (
          <div
            style={{
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 11, marginTop: 4,
              color: avg1h >= 0 ? "#00FF94" : "#FF2060",
            }}
          >
            {fmtPct(avg1h)}
          </div>
        )}
      </StatCard>

      {/* ── Тренд портфеля ── */}
      <StatCard style={{ gridColumn: "2 / 4", gridRow: 2 }} accentColor="#4B69FF">
        <div style={LBL}>Тренд портфеля</div>

        {/* Segmented bar */}
        <div
          style={{
            display: "flex", height: 6, borderRadius: 99, overflow: "hidden",
            background: "rgba(255,255,255,0.07)", marginBottom: 8,
          }}
        >
          <motion.div
            style={{ height: "100%", background: "#00FF94" }}
            initial={{ width: 0 }}
            animate={{ width: `${(upCount      / total) * 100}%` }}
            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          />
          <motion.div
            style={{ height: "100%", background: "rgba(255,255,255,0.18)" }}
            initial={{ width: 0 }}
            animate={{ width: `${(neutralCount / total) * 100}%` }}
            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1], delay: 0.05 }}
          />
          <motion.div
            style={{ height: "100%", background: "#FF2060" }}
            initial={{ width: 0 }}
            animate={{ width: `${(downCount    / total) * 100}%` }}
            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1], delay: 0.1 }}
          />
        </div>

        <div
          style={{
            display: "flex", justifyContent: "space-between",
            fontFamily: "JetBrains Mono, monospace", fontSize: 10,
          }}
        >
          <span style={{ color: "#00FF94" }}>↑ {upCount} растут</span>
          <span style={{ color: "rgba(255,255,255,0.4)" }}>— {neutralCount} без изм.</span>
          <span style={{ color: "#FF2060" }}>↓ {downCount} падают</span>
        </div>
      </StatCard>
    </motion.div>
  );
}

// ─── CasesTable ───────────────────────────────────────────────────────────────
function CasesTable({ cases }: { cases: Item[] }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1], delay: 0.12 }}
      style={{ ...GLASS, marginTop: 14, overflow: "hidden" }}
    >
      {/* Header */}
      <div
        style={{
          padding: "12px 16px",
          borderBottom: "1px solid rgba(255,255,255,0.06)",
          display: "flex", alignItems: "center",
        }}
      >
        <span
          style={{
            fontSize: 13, fontWeight: 600, color: "#EDF0F7",
            fontFamily: "'Rajdhani', sans-serif", letterSpacing: "0.04em",
          }}
        >
          Кейсы
          <span style={{ fontSize: 11, fontWeight: 400, color: "rgba(255,255,255,0.35)", marginLeft: 6 }}>
            ({cases.length})
          </span>
        </span>
      </div>

      {/* Column headers */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 90px 60px 60px 60px",
          padding: "6px 16px",
          borderBottom: "1px solid rgba(255,255,255,0.05)",
          fontSize: 10, fontWeight: 600,
          textTransform: "uppercase", letterSpacing: "0.1em",
          color: "rgba(255,255,255,0.28)",
        }}
      >
        <span>Предмет</span>
        <span style={{ textAlign: "right" }}>Цена</span>
        <span style={{ textAlign: "right" }}>1ч</span>
        <span style={{ textAlign: "right" }}>24ч</span>
        <span style={{ textAlign: "right" }}>Объём</span>
      </div>

      {/* Rows */}
      {cases.map((item, i) => (
        <div
          key={item.id}
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 90px 60px 60px 60px",
            alignItems: "center",
            padding: "9px 16px",
            borderBottom: i < cases.length - 1 ? "1px solid rgba(255,255,255,0.04)" : "none",
            cursor: "pointer",
            transition: "background 0.12s",
          }}
          onMouseEnter={e => (e.currentTarget.style.background = "rgba(255,255,255,0.03)")}
          onMouseLeave={e => (e.currentTarget.style.background = "")}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          onClick={() => (window as any).openItemDetail?.(item.name, item.appid ?? 730)}
        >
          <span
            title={item.name}
            style={{
              fontSize: 13, fontWeight: 500, color: "rgba(149,172,190,0.9)",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}
          >
            {item.name}
          </span>
          <span
            style={{
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 12, fontWeight: 700, color: "#EDF0F7", textAlign: "right",
            }}
          >
            {item.price ? `$${item.price.toFixed(2)}` : "—"}
          </span>
          <div style={{ textAlign: "right" }}><PctChip value={item.pct1h} /></div>
          <div style={{ textAlign: "right" }}><PctChip value={item.pct24h} /></div>
          <span
            style={{
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 11, color: "rgba(255,255,255,0.35)", textAlign: "right",
            }}
          >
            {item.volume ?? "—"}
          </span>
        </div>
      ))}
    </motion.div>
  );
}

// ─── Demo items (shown when no real inventory is loaded) ──────────────────────
const DEMO_ITEMS: Item[] = [
  {
    id: 1, name: "AK-47 | Redline (Field-Tested)",
    weapon: "AK-47", skin: "Redline", wear: "Field-Tested",
    price: 14.50, rarity: "classified", float: "0.1423", volume: "2 814",
    stattrak: false, pattern: null, imageUrl: null,
    pct1h: 1.2, pct24h: -0.8, notify: false, appid: 730, isCase: false,
  },
  {
    id: 2, name: "AWP | Dragon Lore (Factory New)",
    weapon: "AWP", skin: "Dragon Lore", wear: "Factory New",
    price: 1850.00, rarity: "covert", float: "0.0082", volume: "12",
    stattrak: false, pattern: 661, imageUrl: null,
    pct1h: -2.1, pct24h: -5.3, notify: false, appid: 730, isCase: false,
  },
  {
    id: 3, name: "★ StatTrak™ Karambit | Fade (Factory New)",
    weapon: "★ Karambit", skin: "Fade", wear: "Factory New",
    price: 620.00, rarity: "contraband", float: "0.0314", volume: "38",
    stattrak: true, pattern: 1000, imageUrl: null,
    pct1h: 0.5, pct24h: 2.1, notify: false, appid: 730, isCase: false,
  },
  {
    id: 4, name: "M4A4 | Howl (Field-Tested)",
    weapon: "M4A4", skin: "Howl", wear: "Field-Tested",
    price: 2100.00, rarity: "contraband", float: "0.4312", volume: "7",
    stattrak: false, pattern: null, imageUrl: null,
    pct1h: 0.0, pct24h: 0.3, notify: false, appid: 730, isCase: false,
  },
  {
    id: 5, name: "Desert Eagle | Blaze (Factory New)",
    weapon: "Desert Eagle", skin: "Blaze", wear: "Factory New",
    price: 89.00, rarity: "classified", float: "0.0701", volume: "423",
    stattrak: false, pattern: null, imageUrl: null,
    pct1h: 3.4, pct24h: 7.2, notify: false, appid: 730, isCase: false,
  },
  {
    id: 6, name: "P90 | Neoqueen (Minimal Wear)",
    weapon: "P90", skin: "Neoqueen", wear: "Minimal Wear",
    price: 1.20, rarity: "restricted", float: "0.0912", volume: "414",
    stattrak: false, pattern: null, imageUrl: null,
    pct1h: -0.5, pct24h: -1.2, notify: false, appid: 730, isCase: false,
  },
  {
    id: 7, name: "MP5-SD | Phosphor (Field-Tested)",
    weapon: "MP5-SD", skin: "Phosphor", wear: "Field-Tested",
    price: 3.20, rarity: "milspec", float: "0.2241", volume: "881",
    stattrak: false, pattern: null, imageUrl: null,
    pct1h: null, pct24h: 0.8, notify: false, appid: 730, isCase: false,
  },
  {
    id: 8, name: "G3SG1 | Green Cell (Well-Worn)",
    weapon: "G3SG1", skin: "Green Cell", wear: "Well-Worn",
    price: 0.03, rarity: "consumer", float: "0.3712", volume: "285",
    stattrak: false, pattern: null, imageUrl: null,
    pct1h: null, pct24h: null, notify: false, appid: 730, isCase: false,
  },
];

// ─── InventoryPage ────────────────────────────────────────────────────────────
export default function InventoryPage({
  initialItems,
  embedded = false,
}: {
  initialItems?: Item[];
  embedded?: boolean;
}) {
  const shouldReduceMotion = useReducedMotion();
  const [items] = useState<Item[]>(() => initialItems ?? DEMO_ITEMS);
  const [filters, setFilters] = useState<Filters>(FILTERS_EMPTY);
  const [selectedId, setSelectedId] = useState<string | number | null>(null);

  const selectedItem = useMemo(
    () => items.find(i => i.id === selectedId) ?? null,
    [items, selectedId],
  );
  const closeDetail = useCallback(() => setSelectedId(null), []);

  const { skins, cases } = useMemo(
    () => ({
      skins: items.filter(i => !i.isCase),
      cases: items.filter(i =>  i.isCase),
    }),
    [items],
  );

  const filteredSkins = useMemo(() => {
    const q = filters.search.trim().toLowerCase();
    return skins.filter(item => {
      if (q && !item.name.toLowerCase().includes(q)) return false;
      if (filters.type   && getType(item) !== filters.type)     return false;
      if (filters.wear   && item.wear     !== filters.wear)     return false;
      if (filters.rarity && item.rarity   !== filters.rarity)   return false;
      return true;
    });
  }, [skins, filters]);

  return (
    <div style={{ width: "100%", paddingBottom: 32 }}>

      {/* Standalone header */}
      {!embedded && (
        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y:   0 }}
          transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
          style={{ marginBottom: 24 }}
        >
          <h2
            style={{
              fontFamily: "'Rajdhani', sans-serif",
              fontSize: 28, fontWeight: 700,
              color: "#EDF0F7", margin: 0, letterSpacing: "0.02em",
            }}
          >
            Инвентарь
          </h2>
          <p
            style={{
              fontSize: 12, color: "rgba(255,255,255,0.38)",
              fontFamily: "JetBrains Mono, monospace", marginTop: 4,
            }}
          >
            {skins.length} скинов · цены обновляются в реальном времени
          </p>
        </motion.div>
      )}

      {/* ── Filter bar ── */}
      {skins.length > 0 && (
        <FilterBar
          filters={filters}
          onChange={setFilters}
          totalVisible={filteredSkins.length}
          totalAll={skins.length}
        />
      )}

      {/* ── Skin Card Grid + AnimatePresence ── */}
      {/*
        Plain div — no layout animation on the container. Since SkinCards no
        longer use the `layout` prop, there is nothing to propagate upward, and
        a motion.div layout="position" here would just add unnecessary overhead.
        AnimatePresence mode="popLayout" instantly removes exiting cards from the
        DOM so the remaining cards reflow via the browser's normal layout pass.
      */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))",
          gap: 10,
        }}
      >
        <AnimatePresence mode="popLayout">
          {filteredSkins.map((item, index) => (
            <SkinCard
              key={item.id}
              item={item}
              layoutIndex={index}
              isSelected={selectedId === item.id}
              onClick={() => setSelectedId(item.id)}
            />
          ))}
        </AnimatePresence>
      </div>

      {/* Empty state */}
      {filteredSkins.length === 0 && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.1 }}
          style={{
            ...GLASS,
            padding: "48px 32px",
            textAlign: "center",
            marginTop: 16,
          }}
        >
          <div style={{ fontSize: 13, color: "rgba(255,255,255,0.4)", marginBottom: 8 }}>
            Инвентарь пуст
          </div>
          <div style={{ fontSize: 11, color: "rgba(255,255,255,0.22)", fontFamily: "JetBrains Mono, monospace" }}>
            Привяжи Steam аккаунт для отслеживания скинов
          </div>
        </motion.div>
      )}

      {/* Cases */}
      {cases.length > 0 && <CasesTable cases={cases} />}

      {/* ── Detail modal (shared-element expansion via layoutId) ── */}
      <AnimatePresence>
        {selectedItem && (
          <DetailModal
            key={`detail-${selectedItem.id}`}
            item={selectedItem}
            onClose={closeDetail}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
