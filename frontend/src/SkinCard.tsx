/**
 * SkinCard — Elite Trader Dark
 *
 * Domain #9  React Performance
 *   · Wrapped in React.memo with custom comparison (skips re-render when
 *     price/pct fields haven't changed)
 *   · Image src deferred until the card enters the viewport via useInView
 *     (200 px pre-load margin so images are ready before the user sees them)
 *   · img decode="async" + loading="lazy" for the browser's native pipeline
 *
 * Domain #10  Web Guidelines — Interactive states
 *   · whileHover: scale(1.03) + y(-8px) via spring physics (feels physical)
 *   · boxShadow transitions from near-zero to a rarity-colored halo (0.2s ease)
 *   · whileTap: scale(0.97) for press feedback within 100 ms (HIG standard)
 *   · Rarity border brightens on hover via CSS transition (GPU-composited)
 *   · Image scales up 1.08× inside its container on hover (CSS transform)
 *   · All motion respects prefers-reduced-motion via useReducedMotion
 */

import { memo, useState, useRef, useEffect, useCallback } from "react";
import { motion, useInView, useReducedMotion } from "framer-motion";

// ─── Shared Item type (exported for InventoryPage) ────────────────────────────
export interface SkinItem {
  id:       number | string;
  name:     string;
  weapon:   string;
  skin:     string;
  wear:     string;
  price:    number;
  rarity:   string;
  float:    string;
  volume:   string;
  stattrak: boolean;
  pattern:  number | null;
  imageUrl: string | null;
  pct1h:    number | null;
  pct24h:   number | null;
  notify:   boolean;
  appid:    number;
  isCase:   boolean;
}

// ─── Design tokens (Elite Trader Dark) ───────────────────────────────────────
const GLASS: React.CSSProperties = {
  background:           "rgba(13, 17, 32, 0.65)",
  backdropFilter:       "blur(20px)",
  WebkitBackdropFilter: "blur(20px)",
  border:               "1px solid rgba(255,255,255,0.08)",
  borderRadius:         16,
};

const RARITY: Record<string, { label: string; color: string }> = {
  consumer:   { label: "Ширпотреб",     color: "#A8A8A8" },
  industrial: { label: "Промышленное",  color: "#6496E1" },
  milspec:    { label: "Армейское",     color: "#4B69FF" },
  restricted: { label: "Запрещённое",   color: "#8847FF" },
  classified: { label: "Засекреченное", color: "#D32CE6" },
  covert:     { label: "Тайное",        color: "#EB4B4B" },
  contraband: { label: "Контрабанда",   color: "#E4AE39" },
};

// Spring for spatial transforms — feels physical, not mechanical
const SPRING_HOVER = { type: "spring" as const, stiffness: 360, damping: 30, mass: 0.7 };

// ─── PctChip ──────────────────────────────────────────────────────────────────
function PctChip({ value }: { value: number | null }) {
  if (value == null)
    return (
      <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, color: "rgba(255,255,255,0.22)" }}>
        —
      </span>
    );
  const up  = value >= 0;
  const str = `${up ? "+" : ""}${value.toFixed(1)}%`;
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

// ─── Lazy image — reveals only when card enters the viewport ──────────────────
function LazySkinImage({
  src,
  alt,
  rarityColor,
}: {
  src: string | null;
  alt: string;
  rarityColor: string;
}) {
  // Domain #9: defer src until this element is ~200 px from the viewport
  const triggerRef  = useRef<HTMLDivElement>(null);
  const isInView    = useInView(triggerRef, { once: true, margin: "200px" });
  const [activeSrc, setActiveSrc] = useState<string | null>(null);
  const [loaded,    setLoaded]    = useState(false);
  const [failed,    setFailed]    = useState(false);

  useEffect(() => {
    if (isInView && src && !activeSrc) setActiveSrc(src);
  }, [isInView, src, activeSrc]);

  const handleLoad  = useCallback(() => setLoaded(true),  []);
  const handleError = useCallback(() => setFailed(true),  []);

  return (
    <div
      ref={triggerRef}
      style={{
        height: 88,
        display: "flex", alignItems: "center", justifyContent: "center",
        borderRadius: 10, overflow: "hidden", marginBottom: 10,
        background: `radial-gradient(ellipse at center, ${rarityColor}12 0%, rgba(255,255,255,0.02) 70%)`,
        border: `1px solid ${rarityColor}18`,
        // Image zoom container — clip the CSS-transition scale so it stays inside the border
        position: "relative",
      }}
    >
      {activeSrc && !failed ? (
        <img
          src={activeSrc}
          alt={alt}
          loading="lazy"
          decoding="async"
          onLoad={handleLoad}
          onError={handleError}
          style={{
            width: "100%", height: "100%", objectFit: "contain",
            // Domain #10: image scales up on parent hover via CSS (parent carries .skin-card class)
            transition: "opacity 0.3s ease, transform 0.35s cubic-bezier(0.22,1,0.36,1)",
            opacity: loaded ? 1 : 0,
            // The parent motion.div's whileHover triggers .skin-card:hover → scale via className
            transform: "scale(1)",
          }}
          className="skin-img"
        />
      ) : (
        // Fallback dot — glowing rarity color
        <div
          style={{
            width: 12, height: 12, borderRadius: "50%",
            background: rarityColor, opacity: 0.45,
            boxShadow: `0 0 16px ${rarityColor}`,
          }}
        />
      )}
    </div>
  );
}

// ─── SkinCard ─────────────────────────────────────────────────────────────────
function SkinCardComponent({
  item,
  onClick,
  layoutIndex = 0,
  isSelected  = false,
}: {
  item:         SkinItem;
  onClick:      () => void;
  layoutIndex?: number;
  isSelected?:  boolean;
}) {
  const r = RARITY[item.rarity] ?? RARITY.consumer;
  const shouldReduceMotion = useReducedMotion();

  const shadowHover = `0 24px 64px ${r.color}40, 0 8px 24px ${r.color}20, 0 0 0 1px ${r.color}2A`;
  const entranceDelay = shouldReduceMotion ? 0 : Math.min(layoutIndex * 0.03, 0.45);

  return (
    <motion.div
      // Shared element transition — DetailModal uses the same layoutId.
      // No `layout` prop here: combining layout + layoutId causes double measurements
      // on every card in the grid, which is the main source of open/close lag.
      layoutId={`sk-${item.id}`}
      initial={shouldReduceMotion ? false : { opacity: 0, y: 18, scale: 0.94 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={
        shouldReduceMotion
          ? { duration: 0 }
          : { type: "spring", stiffness: 420, damping: 38, mass: 0.7, delay: entranceDelay }
      }
      exit={{
        opacity: 0, scale: 0.88, y: -6,
        transition: { duration: 0.14, ease: [0.4, 0, 1, 1] },
      }}
      whileHover={
        isSelected || shouldReduceMotion
          ? {}
          : { scale: 1.03, y: -8, boxShadow: shadowHover }
      }
      whileTap={
        isSelected || shouldReduceMotion
          ? {}
          : {
              scale: 0.93, y: 2,
              boxShadow: `0 2px 8px rgba(0,0,0,0.65), inset 0 1px 0 rgba(255,255,255,0.04)`,
              transition: { duration: 0.07 },
            }
      }
      onClick={isSelected ? undefined : onClick}
      className="skin-card"
      style={{
        ...GLASS,
        // Use visibility instead of animating opacity — keeps the card in the grid
        // layout (so nothing reflows) while the layoutId morph takes over in the modal.
        visibility: isSelected ? "hidden" : "visible",
        cursor:     isSelected ? "default" : "pointer",
        position:   "relative",
        padding:    14,
        overflow:   "hidden",
        transition: isSelected ? "none" : "border-color 0.2s ease",
      }}
    >
      {/* ── Rarity gradient top bar ── */}
      <div
        style={{
          position: "absolute", top: 0, left: 0, right: 0, height: 2,
          background: `linear-gradient(90deg, ${r.color} 0%, ${r.color}55 55%, transparent)`,
        }}
      />

      {/* ── Corner ambient glow ── */}
      <div
        style={{
          position: "absolute", top: 0, right: 0,
          width: 80, height: 80, pointerEvents: "none",
          background: `radial-gradient(circle at top right, ${r.color}12 0%, transparent 70%)`,
        }}
      />

      {/* ── Lazy skin image ── */}
      <LazySkinImage
        src={item.imageUrl}
        alt={item.skin || item.name}
        rarityColor={r.color}
      />

      {/* ── Badges ── */}
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center", marginBottom: 6 }}>
        {item.stattrak && (
          <span
            style={{
              fontSize: 9, fontWeight: 700, textTransform: "uppercase",
              letterSpacing: "0.06em", padding: "2px 5px", borderRadius: 4,
              color: "#CF6A32", background: "#CF6A3218", border: "1px solid #CF6A3230",
            }}
          >
            ST™
          </span>
        )}
        <span
          style={{
            fontSize: 9, fontWeight: 700, textTransform: "uppercase",
            letterSpacing: "0.06em", padding: "2px 5px", borderRadius: 4,
            color: r.color, background: `${r.color}18`, border: `1px solid ${r.color}30`,
          }}
        >
          {r.label}
        </span>
      </div>

      {/* ── Weapon name ── */}
      <div
        style={{
          fontFamily: "'Rajdhani', sans-serif",
          fontSize: 15, fontWeight: 700, color: r.color,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          lineHeight: 1.2, marginBottom: 2,
        }}
      >
        {item.weapon}
      </div>

      {/* ── Skin + wear ── */}
      <div
        style={{
          fontSize: 11, color: "rgba(255,255,255,0.42)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          marginBottom: 10,
        }}
      >
        {item.skin}{item.wear ? ` (${item.wear})` : ""}
      </div>

      {/* ── Price + delta chips ── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <span
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 15, fontWeight: 700, color: "#EDF0F7",
          }}
        >
          {item.price ? `$${item.price.toFixed(2)}` : "—"}
        </span>
        <div style={{ display: "flex", gap: 4 }}>
          <PctChip value={item.pct1h}  />
          <PctChip value={item.pct24h} />
        </div>
      </div>

      {/* ── Float + Volume ── */}
      <div
        style={{
          display: "flex", justifyContent: "space-between",
          paddingTop: 8, borderTop: "1px solid rgba(255,255,255,0.06)",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 10, color: "rgba(255,255,255,0.28)",
        }}
      >
        <span>float: {item.float !== "—" ? item.float : "—"}</span>
        <span>vol: {item.volume ?? "—"}</span>
      </div>
    </motion.div>
  );
}

// ─── React.memo with custom equality ─────────────────────────────────────────
// Domain #9: skip re-render when only unrelated parent state changes.
// We compare fields that actually affect visual output.
export const SkinCard = memo(SkinCardComponent, (prev, next) => {
  const a = prev.item;
  const b = next.item;
  return (
    a.id          === b.id          &&
    a.price       === b.price       &&
    a.pct1h       === b.pct1h       &&
    a.pct24h      === b.pct24h      &&
    a.imageUrl    === b.imageUrl    &&
    a.notify      === b.notify      &&
    prev.layoutIndex === next.layoutIndex &&
    prev.isSelected  === next.isSelected
  );
});

SkinCard.displayName = "SkinCard";
