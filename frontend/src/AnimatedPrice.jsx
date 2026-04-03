import { memo, useRef, useEffect, useState, useCallback } from "react";
import { motion, useSpring, useTransform, animate } from "framer-motion";

// ─── Rarity config (mirrors SkinCard.jsx) ────────────────────────────────────
const RARITY = {
  consumer:   { color: "#A8A8A8", glow: null },
  industrial: { color: "#6496E1", glow: "0 0 8px #6496E130" },
  milspec:    { color: "#4B69FF", glow: "0 0 12px #4B69FF40" },
  restricted: { color: "#8847FF", glow: "0 0 16px #8847FF50, 0 0 40px #8847FF18" },
  classified: { color: "#D32CE6", glow: "0 0 18px #D32CE660, 0 0 50px #D32CE620" },
  covert:     { color: "#EB4B4B", glow: "0 0 22px #EB4B4B65, 0 0 60px #EB4B4B22" },
  contraband: { color: "#E4AE39", glow: "0 0 28px #E4AE3970, 0 0 80px #E4AE3928" },
};

// Pulse animation keyframes per rarity tier (only rare+ get the pulse)
const PULSE_TIERS = new Set(["restricted", "classified", "covert", "contraband"]);

// ─── SlotDigit — single digit column that rolls ───────────────────────────────
// React §9: isolated memo component — re-renders only when its digit changes.
const SlotDigit = memo(({ digit, delay = 0 }) => {
  const DIGITS = "0123456789";
  const prevRef = useRef(digit);
  const [displayDigit, setDisplayDigit] = useState(digit);
  const [rolling, setRolling] = useState(false);

  useEffect(() => {
    if (prevRef.current === digit) return;

    setRolling(true);
    // Roll through intermediate digits then land on target
    const from = parseInt(prevRef.current) || 0;
    const to   = parseInt(digit) || 0;
    const steps = ((to - from + 10) % 10) || 10;
    let step = 0;

    const interval = setInterval(() => {
      step++;
      setDisplayDigit(String((from + step) % 10));
      if (step >= steps) {
        clearInterval(interval);
        setRolling(false);
        prevRef.current = digit;
      }
    }, 40 + delay * 8); // stagger by position

    return () => clearInterval(interval);
  }, [digit, delay]);

  return (
    <span
      className="inline-block tabular-nums transition-all"
      style={{
        display: "inline-block",
        transform: rolling ? "translateY(-2px)" : "translateY(0)",
        transition: "transform 0.05s ease",
      }}
    >
      {displayDigit !== undefined ? displayDigit : digit}
    </span>
  );
});
SlotDigit.displayName = "SlotDigit";

// ─── PriceDisplay — splits price into digit columns ──────────────────────────
// React §9: memo + per-digit isolation prevents full re-render on price tick
const PriceDisplay = memo(({ formatted, prevFormatted, rarityColor }) => {
  // Only animate numeric chars; pass through symbols as-is
  const chars = formatted.split("");
  const prevChars = (prevFormatted || formatted).split("");

  return (
    <span className="font-mono font-bold" style={{ color: rarityColor ?? "#EDF0F7" }}>
      {chars.map((ch, i) => {
        const isDigit = /\d/.test(ch);
        if (!isDigit) return <span key={`${i}-${ch}`}>{ch}</span>;
        return (
          <SlotDigit
            key={i}
            digit={ch}
            delay={chars.length - i} // rightmost digits roll fastest
          />
        );
      })}
    </span>
  );
});
PriceDisplay.displayName = "PriceDisplay";

// ─── DeltaBadge — flashes on price change ────────────────────────────────────
const DeltaBadge = memo(({ delta, currency = "USD" }) => {
  const [visible, setVisible] = useState(false);
  const prevDelta = useRef(null);

  useEffect(() => {
    if (delta === null || delta === undefined) return;
    if (delta === prevDelta.current) return;
    prevDelta.current = delta;
    setVisible(true);
    const t = setTimeout(() => setVisible(false), 2800);
    return () => clearTimeout(t);
  }, [delta]);

  if (!visible || delta === null || delta === undefined || delta === 0) return null;

  const up   = delta > 0;
  const sign = up ? "+" : "";
  const fmt  = new Intl.NumberFormat("en-US", {
    style: "currency", currency, minimumFractionDigits: 2,
  }).format(Math.abs(delta));

  return (
    <motion.span
      initial={{ opacity: 0, y: up ? 6 : -6, scale: 0.85 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: up ? -6 : 6 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      className="ml-2 inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold font-mono"
      style={{
        background: up ? "rgba(0,255,148,0.13)" : "rgba(255,32,96,0.13)",
        color:      up ? "#00FF94"              : "#FF2060",
        border:     `1px solid ${up ? "rgba(0,255,148,0.28)" : "rgba(255,32,96,0.28)"}`,
      }}
    >
      {sign}{fmt}
    </motion.span>
  );
});
DeltaBadge.displayName = "DeltaBadge";

// ─── RarityGlowRow — wrapper that pulses for rare+ tiers ──────────────────────
// Perf: only `opacity` and `transform` are animated — GPU-composited, zero repaint.
// boxShadow is STATIC (no animation) to avoid paint on every frame.
const RarityGlowRow = memo(({ rarity = "consumer", children, className = "" }) => {
  const r     = RARITY[rarity] ?? RARITY.consumer;
  const pulse = PULSE_TIERS.has(rarity);

  return (
    <div
      className={`relative rounded-xl ${className}`}
      style={{ border: `1px solid ${r.color}28`, background: `${r.color}08` }}
    >
      {/* Pulsing glow — opacity-only animation (GPU composited, no repaint) */}
      {pulse && (
        <motion.div
          className="pointer-events-none absolute inset-0 rounded-xl"
          style={{
            background: `radial-gradient(ellipse at 30% 50%, ${r.color}20 0%, transparent 65%)`,
          }}
          animate={{ opacity: [1, 0.2, 1] }}
          transition={{ duration: 3.5, repeat: Infinity, ease: "easeInOut" }}
        />
      )}
      {/* Hover lift — transform only (GPU composited) */}
      <motion.div
        whileHover={{ y: -2, transition: { duration: 0.15, ease: "easeOut" } }}
      >
        {children}
      </motion.div>
    </div>
  );
});
RarityGlowRow.displayName = "RarityGlowRow";

// ─── AnimatedPrice — main export ──────────────────────────────────────────────
/**
 * @param {number}  price      - Current price value
 * @param {string}  currency   - ISO 4217 currency code (default "USD")
 * @param {string}  rarity     - CS2 rarity key
 * @param {boolean} showDelta  - Show +/- badge on change
 * @param {string}  className  - Extra Tailwind classes
 */
const AnimatedPrice = memo(
  ({ price, currency = "USD", rarity = "consumer", showDelta = true, className = "" }) => {
    const prevPriceRef  = useRef(price);
    const [delta, setDelta]       = useState(null);
    const [prevFormatted, setPrevFormatted] = useState(null);

    const fmt = useCallback(
      (v) =>
        new Intl.NumberFormat("en-US", {
          style: "currency", currency, minimumFractionDigits: 2,
        }).format(v),
      [currency]
    );

    const formatted = fmt(price);

    useEffect(() => {
      if (prevPriceRef.current === price) return;
      const diff = price - prevPriceRef.current;
      setDelta(diff);
      setPrevFormatted(fmt(prevPriceRef.current));
      prevPriceRef.current = price;
    }, [price, fmt]);

    const r = RARITY[rarity] ?? RARITY.consumer;

    return (
      <span className={`inline-flex items-center gap-1 ${className}`}>
        <PriceDisplay
          formatted={formatted}
          prevFormatted={prevFormatted}
          rarityColor={r.color}
        />
        {showDelta && <DeltaBadge delta={delta} currency={currency} />}
      </span>
    );
  }
);
AnimatedPrice.displayName = "AnimatedPrice";

export default AnimatedPrice;
export { RarityGlowRow };

// ─── Demo ─────────────────────────────────────────────────────────────────────
export function AnimatedPriceDemo() {
  const [items, setItems] = useState([
    { id: 1, name: "AK-47 | Redline",       price: 14.50,   rarity: "classified" },
    { id: 2, name: "AWP | Dragon Lore",      price: 1850.00, rarity: "covert"     },
    { id: 3, name: "Karambit | Fade",        price: 620.00,  rarity: "contraband" },
    { id: 4, name: "M4A4 | Howl",            price: 2100.00, rarity: "contraband" },
    { id: 5, name: "Desert Eagle | Blaze",   price: 89.00,   rarity: "classified" },
    { id: 6, name: "MP5-SD | Phosphor",      price: 3.20,    rarity: "milspec"    },
    { id: 7, name: "P90 | Neoqueen",         price: 1.20,    rarity: "restricted" },
    { id: 8, name: "G3SG1 | Green Cell",     price: 0.03,    rarity: "consumer"   },
  ]);

  // Simulate live price ticks every 2s (like real market data)
  useEffect(() => {
    const interval = setInterval(() => {
      setItems((prev) =>
        prev.map((item) => {
          // Random ±0.5–5% price change
          const pct    = (Math.random() - 0.5) * 0.08;
          const newPrice = Math.max(0.01, +(item.price * (1 + pct)).toFixed(2));
          return { ...item, price: newPrice };
        })
      );
    }, 2200);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="min-h-screen bg-[#080B10] p-8">
      {/* Ambient background glow */}
      <div
        className="pointer-events-none fixed inset-0 opacity-30"
        style={{
          background:
            "radial-gradient(ellipse at 20% 30%, rgba(0,229,255,0.06) 0%, transparent 50%), " +
            "radial-gradient(ellipse at 80% 70%, rgba(176,65,255,0.06) 0%, transparent 50%)",
        }}
      />

      <h2
        className="mb-2 text-2xl font-bold text-slate-100"
        style={{ fontFamily: "'Rajdhani', sans-serif" }}
      >
        CS2 Skin Hub — Live Prices
      </h2>
      <p className="mb-6 text-xs text-slate-500 font-mono">
        Prices update every 2.2s · digits animate slot-machine style · hover rows
      </p>

      <div className="flex flex-col gap-2 max-w-xl">
        {items.map((item) => (
          <RarityGlowRow key={item.id} rarity={item.rarity} className="px-4 py-3">
            <div className="flex items-center justify-between gap-4">
              {/* Name */}
              <span
                className="text-sm font-semibold truncate"
                style={{
                  fontFamily: "'Rajdhani', sans-serif",
                  color: (RARITY[item.rarity] ?? RARITY.consumer).color,
                }}
              >
                {item.name}
              </span>

              {/* Animated price */}
              <AnimatedPrice
                price={item.price}
                rarity={item.rarity}
                showDelta
                className="text-sm shrink-0"
              />
            </div>
          </RarityGlowRow>
        ))}
      </div>

      <p className="mt-8 text-[11px] text-slate-600 font-mono">
        React.memo · per-digit slot animation · Framer Motion pulse · delta badge
      </p>
    </div>
  );
}
