import { useState, memo } from "react";

// ─── Mesh gradient definitions ────────────────────────────────────────────────
// Built from skill domains: style "dark gaming glassmorphism", color "gaming
// dark cyberpunk deep-space", prompt "CSS mesh gradient dark mode".
// Each variant is a stack of radial-gradients — the closest CSS approximation
// to true mesh gradients (spec still draft). Nodes are positioned intentionally
// off-center to create tension and visual movement.

const VARIANTS = [
  {
    id: "cyberpunk",
    name: "Cyberpunk Neon",
    tags: ["Cyberpunk Dark", "Gaming", "High Energy"],
    description: "Электрический cyan против пурпура. Максимальный контраст — для хабов с агрессивной айдентикой.",
    css: `
      radial-gradient(ellipse 80% 60% at 15% 25%,  #00E5FF18 0%, transparent 60%),
      radial-gradient(ellipse 60% 50% at 85% 15%,  #B041FF22 0%, transparent 55%),
      radial-gradient(ellipse 70% 55% at 70% 80%,  #FF206018 0%, transparent 60%),
      radial-gradient(ellipse 50% 40% at 30% 75%,  #00E5FF10 0%, transparent 50%),
      radial-gradient(ellipse 90% 70% at 50% 50%,  #0D0F1A00 0%, #080B1400 100%),
      linear-gradient(135deg, #060810 0%, #0A0D18 50%, #06080E 100%)
    `.replace(/\n\s+/g, " ").trim(),
    accent1: "#00E5FF",
    accent2: "#B041FF",
    accent3: "#FF2060",
    bg: "#06080E",
    nodes: [
      { x: "15%", y: "25%", color: "#00E5FF", size: 320, opacity: 0.18 },
      { x: "85%", y: "15%", color: "#B041FF", size: 280, opacity: 0.22 },
      { x: "70%", y: "80%", color: "#FF2060", size: 300, opacity: 0.16 },
      { x: "30%", y: "75%", color: "#00E5FF", size: 200, opacity: 0.10 },
      { x: "55%", y: "48%", color: "#B041FF", size: 180, opacity: 0.08 },
    ],
  },
  {
    id: "deepspace",
    name: "Deep Space Aurora",
    tags: ["Deep Space", "Atmospheric", "Cinematic"],
    description: "Тёмный индиго с авроральными переходами. Спокойная глубина — для аналитических и трейдинговых интерфейсов.",
    css: `
      radial-gradient(ellipse 70% 55% at 10% 40%,  #1A4FCC20 0%, transparent 65%),
      radial-gradient(ellipse 55% 45% at 88% 25%,  #0EA5E922 0%, transparent 60%),
      radial-gradient(ellipse 65% 50% at 60% 85%,  #7C3AED1A 0%, transparent 60%),
      radial-gradient(ellipse 45% 35% at 40% 15%,  #06B6D415 0%, transparent 50%),
      radial-gradient(ellipse 80% 60% at 75% 55%,  #1E3A5F12 0%, transparent 65%),
      linear-gradient(160deg, #050810 0%, #080D1A 40%, #05080F 100%)
    `.replace(/\n\s+/g, " ").trim(),
    accent1: "#0EA5E9",
    accent2: "#7C3AED",
    accent3: "#06B6D4",
    bg: "#050810",
    nodes: [
      { x: "10%", y: "40%", color: "#1A4FCC", size: 340, opacity: 0.20 },
      { x: "88%", y: "25%", color: "#0EA5E9", size: 260, opacity: 0.22 },
      { x: "60%", y: "85%", color: "#7C3AED", size: 300, opacity: 0.18 },
      { x: "40%", y: "15%", color: "#06B6D4", size: 220, opacity: 0.15 },
      { x: "75%", y: "55%", color: "#1E3A5F", size: 360, opacity: 0.12 },
    ],
  },
  {
    id: "obsidian",
    name: "Obsidian Ember",
    tags: ["Premium Dark", "Luxury", "Warm Contrast"],
    description: "Угольный фон с тлеющими янтарными и алыми узлами. Для дорогих предметов и редкого инвентаря.",
    css: `
      radial-gradient(ellipse 65% 50% at 20% 70%,  #E4AE3920 0%, transparent 60%),
      radial-gradient(ellipse 55% 42% at 80% 20%,  #EB4B4B1C 0%, transparent 55%),
      radial-gradient(ellipse 70% 52% at 55% 30%,  #FF860018 0%, transparent 60%),
      radial-gradient(ellipse 45% 35% at 85% 75%,  #E4AE3914 0%, transparent 50%),
      radial-gradient(ellipse 60% 45% at 25% 20%,  #6B1D1D10 0%, transparent 55%),
      linear-gradient(145deg, #080608 0%, #0F0A08 45%, #080507 100%)
    `.replace(/\n\s+/g, " ").trim(),
    accent1: "#E4AE39",
    accent2: "#EB4B4B",
    accent3: "#FF8600",
    bg: "#080608",
    nodes: [
      { x: "20%", y: "70%", color: "#E4AE39", size: 310, opacity: 0.20 },
      { x: "80%", y: "20%", color: "#EB4B4B", size: 260, opacity: 0.18 },
      { x: "55%", y: "30%", color: "#FF8600", size: 290, opacity: 0.16 },
      { x: "85%", y: "75%", color: "#E4AE39", size: 200, opacity: 0.14 },
      { x: "25%", y: "20%", color: "#6B1D1D", size: 240, opacity: 0.10 },
    ],
  },
];

// ─── MeshNode — single gradient blob (SVG-based for precision) ────────────────
const MeshNode = memo(({ x, y, color, size, opacity }) => (
  <div
    className="pointer-events-none absolute rounded-full"
    style={{
      left: x, top: y,
      width: size, height: size,
      transform: "translate(-50%, -50%)",
      background: `radial-gradient(circle, ${color} 0%, transparent 70%)`,
      opacity,
      filter: "blur(40px)",
    }}
  />
));
MeshNode.displayName = "MeshNode";

// ─── CopyButton ───────────────────────────────────────────────────────────────
const CopyButton = memo(({ text, label = "Копировать CSS" }) => {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
      className="rounded-lg px-3 py-1.5 text-[11px] font-semibold font-mono transition-all"
      style={{
        background: copied ? "rgba(0,255,148,0.15)" : "rgba(255,255,255,0.07)",
        border:     copied ? "1px solid rgba(0,255,148,0.4)" : "1px solid rgba(255,255,255,0.12)",
        color:      copied ? "#00FF94" : "rgba(255,255,255,0.6)",
      }}
    >
      {copied ? "✓ Скопировано" : label}
    </button>
  );
});
CopyButton.displayName = "CopyButton";

// ─── GradientCard — one variant ───────────────────────────────────────────────
const GradientCard = memo(({ variant, isActive, onSelect }) => {
  return (
    <div
      className="flex flex-col overflow-hidden rounded-2xl transition-all duration-300"
      style={{
        border: isActive
          ? `1px solid ${variant.accent1}55`
          : "1px solid rgba(255,255,255,0.08)",
        boxShadow: isActive
          ? `0 0 32px ${variant.accent1}20, 0 8px 40px rgba(0,0,0,0.5)`
          : "0 4px 20px rgba(0,0,0,0.4)",
        transform: isActive ? "translateY(-4px)" : "none",
      }}
    >
      {/* Preview */}
      <div
        className="relative h-52 cursor-pointer overflow-hidden"
        style={{ background: variant.bg }}
        onClick={() => onSelect(variant.id)}
      >
        {/* Mesh nodes (SVG blobs) */}
        {variant.nodes.map((n, i) => (
          <MeshNode key={i} {...n} />
        ))}

        {/* Glass demo card overlay */}
        <div className="absolute inset-0 flex items-center justify-center">
          <div
            className="rounded-xl px-5 py-3 text-center"
            style={{
              background: "rgba(255,255,255,0.04)",
              backdropFilter: "blur(12px)",
              border: "1px solid rgba(255,255,255,0.08)",
              boxShadow: `0 8px 32px rgba(0,0,0,0.4), 0 0 20px ${variant.accent1}18`,
            }}
          >
            <div className="font-mono text-[10px] uppercase tracking-widest mb-1"
              style={{ color: variant.accent1 }}>
              {variant.name}
            </div>
            <div className="font-bold text-white text-sm" style={{ fontFamily: "'Rajdhani',sans-serif" }}>
              AK-47 | Redline
            </div>
            <div className="font-mono text-xs mt-1" style={{ color: variant.accent2 }}>
              $14.50
            </div>
          </div>
        </div>

        {/* Active badge */}
        {isActive && (
          <div className="absolute top-3 right-3 rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-widest"
            style={{ background: `${variant.accent1}25`, color: variant.accent1, border: `1px solid ${variant.accent1}40` }}>
            выбран
          </div>
        )}

        {/* Color palette strip */}
        <div className="absolute bottom-0 inset-x-0 flex h-1">
          <div className="flex-1" style={{ background: variant.accent1 }} />
          <div className="flex-1" style={{ background: variant.accent2 }} />
          <div className="flex-1" style={{ background: variant.accent3 }} />
        </div>
      </div>

      {/* Info panel */}
      <div className="flex flex-col gap-3 p-4"
        style={{ background: "rgba(10,12,18,0.95)" }}>
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="font-bold text-sm text-slate-100" style={{ fontFamily: "'Rajdhani',sans-serif" }}>
              {variant.name}
            </div>
            <div className="mt-0.5 flex flex-wrap gap-1">
              {variant.tags.map(t => (
                <span key={t} className="rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-widest"
                  style={{ background: `${variant.accent1}12`, color: variant.accent1, border: `1px solid ${variant.accent1}25` }}>
                  {t}
                </span>
              ))}
            </div>
          </div>
          <div className="flex gap-1.5 shrink-0">
            {[variant.accent1, variant.accent2, variant.accent3].map(c => (
              <div key={c} className="h-4 w-4 rounded-full border border-white/10"
                style={{ background: c, boxShadow: `0 0 6px ${c}60` }} />
            ))}
          </div>
        </div>

        <p className="text-xs leading-relaxed text-slate-500">{variant.description}</p>

        <div className="flex items-center gap-2">
          <CopyButton text={`background:\n  ${variant.css};`} />
          <button
            onClick={() => onSelect(variant.id)}
            className="rounded-lg px-3 py-1.5 text-[11px] font-semibold font-mono transition-all"
            style={{
              background: isActive ? `${variant.accent1}20` : "transparent",
              border:     isActive ? `1px solid ${variant.accent1}45` : "1px solid rgba(255,255,255,0.1)",
              color:      isActive ? variant.accent1 : "rgba(255,255,255,0.45)",
            }}
          >
            {isActive ? "✓ Активен" : "Применить"}
          </button>
        </div>
      </div>
    </div>
  );
});
GradientCard.displayName = "GradientCard";

// ─── MeshGradientDemo — full page ─────────────────────────────────────────────
export function MeshGradientDemo() {
  const [activeId, setActiveId] = useState("cyberpunk");
  const active = VARIANTS.find(v => v.id === activeId);

  return (
    // Live preview — entire page background changes to selected mesh
    <div
      className="min-h-screen transition-all duration-700"
      style={{ background: active.css }}
    >
      <div className="mx-auto max-w-5xl px-8 py-10">
        <div className="mb-2 flex items-center gap-3">
          <div className="h-px flex-1 opacity-20" style={{ background: active.accent1 }} />
          <h2 className="font-bold text-slate-100" style={{ fontFamily: "'Rajdhani',sans-serif", fontSize: 22 }}>
            Mesh Gradient — Dark Theme
          </h2>
          <div className="h-px flex-1 opacity-20" style={{ background: active.accent1 }} />
        </div>
        <p className="mb-8 text-center text-[11px] font-mono text-slate-500">
          UI UX Pro Max · domain: style + color + prompt · 3 варианта для тёмной темы
        </p>

        {/* Cards grid */}
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
          {VARIANTS.map(v => (
            <GradientCard
              key={v.id}
              variant={v}
              isActive={v.id === activeId}
              onSelect={setActiveId}
            />
          ))}
        </div>

        {/* CSS output */}
        <div className="mt-8 overflow-hidden rounded-xl"
          style={{ background: "rgba(0,0,0,0.5)", border: "1px solid rgba(255,255,255,0.07)" }}>
          <div className="flex items-center justify-between px-4 py-2.5"
            style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
            <span className="font-mono text-[11px]" style={{ color: active.accent1 }}>
              CSS · {active.name}
            </span>
            <CopyButton text={`background:\n  ${active.css};`} label="Копировать" />
          </div>
          <pre className="overflow-x-auto px-4 py-3 text-[11px] leading-relaxed text-slate-400 font-mono">
{`background:
  ${active.css
    .split("),")
    .join("),\n  ")};`}
          </pre>
        </div>

        {/* Usage note */}
        <p className="mt-4 text-center text-[10px] text-slate-600 font-mono">
          Нажми «Применить» — фон страницы переключается live · Нажми «Копировать CSS» — в буфер
        </p>
      </div>
    </div>
  );
}

export default MeshGradientDemo;
