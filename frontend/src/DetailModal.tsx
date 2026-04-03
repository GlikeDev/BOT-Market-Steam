/**
 * DetailModal — shared-element expansion of a SkinCard into full detail view
 *
 * React Native guidelines #7 (Navigation Direction) + #8 (Shared Element Transition)
 * applied to Web via Framer Motion layoutId:
 *   - The card's outer motion.div and this modal's outer motion.div share the
 *     same layoutId (`sk-${item.id}`).  Framer Motion records the card's
 *     bounding rect, then morphs its shape/position to fill the centered modal.
 *   - Content inside fades in after the shape transition starts (delay: 0.1s)
 *     so the user sees the morph first, then the new information appears.
 *   - On close: content fades out first, then shape morphs back to the card.
 *   - Spring physics (stiffness 320, damping 34) give a physical, not robotic feel.
 */

import { memo, useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import type { SkinItem } from "./SkinCard";

// ─── Types ────────────────────────────────────────────────────────────────────
interface PricePoint { day: number; price: number; }

// ─── Design tokens ────────────────────────────────────────────────────────────
const RARITY: Record<string, { label: string; color: string }> = {
  consumer:   { label: "Ширпотреб",     color: "#A8A8A8" },
  industrial: { label: "Промышленное",  color: "#6496E1" },
  milspec:    { label: "Армейское",     color: "#4B69FF" },
  restricted: { label: "Запрещённое",   color: "#8847FF" },
  classified: { label: "Засекреченное", color: "#D32CE6" },
  covert:     { label: "Тайное",        color: "#EB4B4B" },
  contraband: { label: "Контрабанда",   color: "#E4AE39" },
};

const GLASS_DEEP: React.CSSProperties = {
  background:           "rgba(10, 13, 24, 0.94)",
  backdropFilter:       "blur(32px)",
  WebkitBackdropFilter: "blur(32px)",
  border:               "1px solid rgba(255,255,255,0.10)",
  borderRadius:         20,
};

// ─── Price history generator (fallback when API returns nothing) ──────────────
function genHistory(base: number, days = 30): PricePoint[] {
  const pts: PricePoint[] = [];
  let p = base * (0.85 + Math.random() * 0.3);
  for (let i = 0; i < days; i++) {
    p = Math.max(0.01, p * (1 + (Math.random() - 0.49) * 0.06));
    pts.push({ day: i, price: parseFloat(p.toFixed(2)) });
  }
  pts[pts.length - 1].price = base;
  return pts;
}

// ─── PriceChart ───────────────────────────────────────────────────────────────
const PriceChart = memo(function PriceChart({
  history,
  color,
}: {
  history: PricePoint[];
  color:   string;
}) {
  const [hovered, setHovered] = useState<number | null>(null);

  const W = 480, H = 112;
  const PAD = { t: 10, r: 14, b: 26, l: 48 };
  const iW  = W - PAD.l - PAD.r;
  const iH  = H - PAD.t - PAD.b;

  const prices = history.map(d => d.price);
  const minP   = Math.min(...prices);
  const maxP   = Math.max(...prices);
  const range  = maxP - minP || 1;

  const xOf = (i: number) => PAD.l + (i / (history.length - 1)) * iW;
  const yOf = (p: number) => PAD.t + iH - ((p - minP) / range) * iH;

  // Smooth cubic bezier path
  const linePath = history.reduce((acc, d, i) => {
    const x = xOf(i), y = yOf(d.price);
    if (i === 0) return `M ${x} ${y}`;
    const px = xOf(i - 1), py = yOf(history[i - 1].price);
    const cx = (px + x) / 2;
    return `${acc} C ${cx} ${py} ${cx} ${y} ${x} ${y}`;
  }, "");

  const areaPath = `${linePath} L ${xOf(history.length - 1)} ${H - PAD.b} L ${xOf(0)} ${H - PAD.b} Z`;
  const gradId   = `det-${color.replace("#", "")}`;

  const fmt = (v: number) =>
    new Intl.NumberFormat("en-US", {
      style: "currency", currency: "USD", maximumFractionDigits: 2,
    }).format(v);

  const yTicks = [0, 0.5, 1].map(t => ({
    y:     PAD.t + iH * (1 - t),
    label: fmt(minP + range * t),
  }));

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement, MouseEvent>) => {
      const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
      const scaleX = rect.width / W;
      const relX   = e.clientX - rect.left - PAD.l * scaleX;
      const idx    = Math.round((relX / (scaleX * iW)) * (history.length - 1));
      setHovered(Math.max(0, Math.min(history.length - 1, idx)));
    },
    [history.length, iW],
  );

  return (
    <div style={{ position: "relative", userSelect: "none" }}
         onMouseLeave={() => setHovered(null)}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: "100%", height: 112 }}
        onMouseMove={handleMouseMove}
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stopColor={color} stopOpacity="0.22" />
            <stop offset="100%" stopColor={color} stopOpacity="0.01" />
          </linearGradient>
          <filter id="det-glow">
            <feGaussianBlur stdDeviation="1.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Grid lines + Y labels */}
        {yTicks.map((t, i) => (
          <g key={i}>
            <line
              x1={PAD.l} x2={W - PAD.r} y1={t.y} y2={t.y}
              stroke="rgba(255,255,255,0.06)"
              strokeWidth="1" strokeDasharray="3 4"
            />
            <text
              x={PAD.l - 6} y={t.y + 4}
              textAnchor="end" fontSize="9"
              fill="rgba(255,255,255,0.28)"
              fontFamily="JetBrains Mono, monospace"
            >
              {t.label}
            </text>
          </g>
        ))}

        {/* Area fill */}
        <path d={areaPath} fill={`url(#${gradId})`} />

        {/* Line with glow */}
        <path
          d={linePath} fill="none"
          stroke={color} strokeWidth="1.8"
          filter="url(#det-glow)"
          strokeLinecap="round" strokeLinejoin="round"
        />

        {/* Hover crosshair */}
        {hovered !== null && (
          <>
            <line
              x1={xOf(hovered)} x2={xOf(hovered)}
              y1={PAD.t}         y2={H - PAD.b}
              stroke="rgba(255,255,255,0.18)"
              strokeWidth="1" strokeDasharray="3 3"
            />
            <circle
              cx={xOf(hovered)} cy={yOf(history[hovered].price)}
              r="4" fill={color}
              stroke="#0A0D18" strokeWidth="2"
              style={{ filter: `drop-shadow(0 0 5px ${color})` }}
            />
          </>
        )}

        {/* X-axis labels */}
        {[0, Math.floor((history.length - 1) / 2), history.length - 1].map(i => (
          <text
            key={i} x={xOf(i)} y={H - 4}
            textAnchor="middle" fontSize="9"
            fill="rgba(255,255,255,0.22)"
            fontFamily="JetBrains Mono, monospace"
          >
            {i === history.length - 1 ? "сейчас" : `-${history.length - 1 - i}д`}
          </text>
        ))}
      </svg>

      {/* Floating price tooltip */}
      {hovered !== null && (
        <div style={{
          position:    "absolute",
          top:         4,
          left:        `${(xOf(hovered) / W) * 100}%`,
          transform:   "translateX(-50%)",
          background:  "rgba(10,13,24,0.96)",
          border:      `1px solid ${color}40`,
          borderRadius: 6,
          padding:     "3px 8px",
          fontSize:    11,
          fontFamily:  "JetBrains Mono, monospace",
          color,
          fontWeight:  700,
          whiteSpace:  "nowrap",
          pointerEvents: "none",
        }}>
          {fmt(history[hovered].price)}
        </div>
      )}
    </div>
  );
});

// ─── Chip helper ──────────────────────────────────────────────────────────────
function PctChip({ value, label }: { value: number; label: string }) {
  const up = value >= 0;
  return (
    <span style={{
      fontFamily:   "JetBrains Mono, monospace",
      fontSize:     11, fontWeight: 700,
      padding:      "3px 8px", borderRadius: 99,
      color:        up ? "#00FF94" : "#FF2060",
      background:   up ? "rgba(0,255,148,0.12)" : "rgba(255,32,96,0.12)",
      border:       `1px solid ${up ? "rgba(0,255,148,0.25)" : "rgba(255,32,96,0.25)"}`,
    }}>
      {up ? "+" : ""}{value.toFixed(1)}% {label}
    </span>
  );
}

// ─── DetailModal ──────────────────────────────────────────────────────────────
export const DetailModal = memo(function DetailModal({
  item,
  onClose,
}: {
  item:    SkinItem;
  onClose: () => void;
}) {
  const r = RARITY[item.rarity] ?? RARITY.consumer;
  const [imgFailed, setImgFailed] = useState(false);

  // Price history — try API first, fall back to generated sparkline
  const [history, setHistory] = useState<PricePoint[]>(() => genHistory(item.price));

  useEffect(() => {
    fetch(`/api/prices/${encodeURIComponent(item.name)}?days=30`)
      .then(res => (res.ok ? res.json() : null))
      .then((data: unknown) => {
        if (Array.isArray(data) && data.length > 1) {
          setHistory(
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            (data as any[]).map((d, i) => ({
              day:   i,
              price: typeof d.price === "number" ? d.price : parseFloat(d.price),
            })),
          );
        }
      })
      .catch(() => { /* keep generated */ });
  }, [item.name, item.price]);

  // Escape key to close
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", h);
    return () => document.removeEventListener("keydown", h);
  }, [onClose]);

  return (
    <>
      {/* ── Backdrop ── */}
      <motion.div
        key="detail-backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.22 }}
        onClick={onClose}
        style={{
          position: "fixed", inset: 0,
          background: "rgba(0, 0, 0, 0.72)",
          backdropFilter:       "blur(6px)",
          WebkitBackdropFilter: "blur(6px)",
          zIndex: 50,
        }}
      />

      {/* ── Centering shell — no CSS transforms so layoutId moves freely ── */}
      <div style={{
        position: "fixed", inset: 0,
        display:  "flex", alignItems: "center", justifyContent: "center",
        zIndex: 51, pointerEvents: "none",
      }}>
        {/*
          Morphing container — shares layoutId with SkinCard.
          Spring transition drives the shape animation;
          content inside fades in separately with a 0.1s delay.
        */}
        <motion.div
          layoutId={`sk-${item.id}`}
          style={{
            ...GLASS_DEEP,
            width: "90vw", maxWidth: 520,
            maxHeight: "88vh",
            overflowY: "auto",
            pointerEvents: "auto",
          }}
          transition={{ type: "spring", stiffness: 320, damping: 34, mass: 0.9 }}
        >
          {/* Content — fades in after shape morph starts */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18, delay: 0.1 }}
            style={{ padding: "18px 20px 22px" }}
          >
            {/* ── Top row: badges + close ── */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
              <div style={{ display: "flex", gap: 5, alignItems: "center", flexWrap: "wrap" }}>
                {item.stattrak && (
                  <span style={{
                    fontSize: 10, fontWeight: 700, textTransform: "uppercase",
                    letterSpacing: "0.06em", padding: "2px 6px", borderRadius: 4,
                    color: "#CF6A32", background: "#CF6A3218", border: "1px solid #CF6A3230",
                  }}>ST™</span>
                )}
                <span style={{
                  fontSize: 10, fontWeight: 700, textTransform: "uppercase",
                  letterSpacing: "0.06em", padding: "2px 6px", borderRadius: 4,
                  color: r.color, background: `${r.color}18`, border: `1px solid ${r.color}30`,
                }}>{r.label}</span>
              </div>
              <button
                onClick={onClose}
                aria-label="Закрыть"
                style={{
                  background: "rgba(255,255,255,0.06)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  borderRadius: 8, cursor: "pointer",
                  color: "rgba(255,255,255,0.55)", fontSize: 16,
                  width: 28, height: 28,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  transition: "background 0.15s",
                }}
                onMouseEnter={e => ((e.target as HTMLElement).style.background = "rgba(255,255,255,0.1)")}
                onMouseLeave={e => ((e.target as HTMLElement).style.background = "rgba(255,255,255,0.06)")}
              >×</button>
            </div>

            {/* ── Skin image ── */}
            <div style={{
              height: 148,
              display: "flex", alignItems: "center", justifyContent: "center",
              borderRadius: 12, marginBottom: 16, overflow: "hidden",
              background: `radial-gradient(ellipse at center, ${r.color}14 0%, rgba(255,255,255,0.02) 70%)`,
              border: `1px solid ${r.color}20`,
              position: "relative",
            }}>
              {/* Rarity accent line */}
              <div style={{
                position: "absolute", top: 0, left: 0, right: 0, height: 2,
                background: `linear-gradient(90deg, ${r.color}, ${r.color}40 60%, transparent)`,
              }} />
              {item.imageUrl && !imgFailed ? (
                <img
                  src={item.imageUrl}
                  alt={item.skin || item.name}
                  style={{ width: "100%", height: "100%", objectFit: "contain" }}
                  onError={() => setImgFailed(true)}
                />
              ) : (
                <div style={{
                  width: 24, height: 24, borderRadius: "50%",
                  background: r.color, opacity: 0.4,
                  boxShadow: `0 0 32px ${r.color}`,
                }} />
              )}
            </div>

            {/* ── Weapon + skin name ── */}
            <div style={{
              fontFamily: "'Rajdhani', sans-serif",
              fontSize: 24, fontWeight: 700, color: r.color,
              lineHeight: 1.15, marginBottom: 3,
            }}>
              {item.weapon}
            </div>
            <div style={{
              fontSize: 13, color: "rgba(255,255,255,0.48)",
              marginBottom: 14,
            }}>
              {item.skin}{item.wear ? ` · ${item.wear}` : ""}
            </div>

            {/* ── Price row ── */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 20 }}>
              <span style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 28, fontWeight: 700, color: "#EDF0F7",
              }}>
                {item.price ? `$${item.price.toFixed(2)}` : "—"}
              </span>
              {item.pct1h  != null && <PctChip value={item.pct1h}  label="1ч"  />}
              {item.pct24h != null && <PctChip value={item.pct24h} label="24ч" />}
            </div>

            {/* ── Price chart ── */}
            <div style={{ marginBottom: 18 }}>
              <div style={{
                fontSize: 9, color: "rgba(255,255,255,0.28)",
                textTransform: "uppercase", letterSpacing: "0.11em",
                fontWeight: 600, marginBottom: 8,
              }}>
                История цен · 30 дней
              </div>
              <PriceChart history={history} color={r.color} />
            </div>

            {/* ── Divider ── */}
            <div style={{ height: 1, background: "rgba(255,255,255,0.07)", marginBottom: 16 }} />

            {/* ── Stats grid ── */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
              {[
                { label: "Float",   value: item.float   !== "—" ? item.float : "—" },
                { label: "Объём",   value: item.volume  ?? "—" },
                { label: "Pattern", value: item.pattern != null ? String(item.pattern) : "—" },
              ].map(stat => (
                <div key={stat.label} style={{
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.06)",
                  borderRadius: 10, padding: "9px 12px",
                }}>
                  <div style={{
                    fontSize: 9, color: "rgba(255,255,255,0.28)",
                    textTransform: "uppercase", letterSpacing: "0.1em",
                    fontWeight: 600, marginBottom: 5,
                  }}>
                    {stat.label}
                  </div>
                  <div style={{
                    fontFamily: "JetBrains Mono, monospace",
                    fontSize: 13, fontWeight: 600, color: "#EDF0F7",
                  }}>
                    {stat.value}
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        </motion.div>
      </div>
    </>
  );
});
