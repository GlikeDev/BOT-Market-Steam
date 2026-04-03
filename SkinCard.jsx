import React, { useState, useCallback, memo } from "react";

// ─── Rarity config ────────────────────────────────────────────────────────────
const RARITY = {
  consumer:    { label: "Consumer",    color: "#A8A8A8", glow: "shadow-[0_0_0px_transparent]",           border: "border-[#A8A8A8]/30" },
  industrial:  { label: "Industrial",  color: "#6496E1", glow: "shadow-[0_0_10px_#6496E140]",            border: "border-[#6496E1]/50" },
  milspec:     { label: "Mil-Spec",    color: "#4B69FF", glow: "shadow-[0_0_14px_#4B69FF50]",            border: "border-[#4B69FF]/60" },
  restricted:  { label: "Restricted",  color: "#8847FF", glow: "shadow-[0_0_18px_#8847FF55]",            border: "border-[#8847FF]/65" },
  classified:  { label: "Classified",  color: "#D32CE6", glow: "shadow-[0_0_22px_#D32CE660]",            border: "border-[#D32CE6]/70" },
  covert:      { label: "Covert",      color: "#EB4B4B", glow: "shadow-[0_0_28px_#EB4B4B65]",            border: "border-[#EB4B4B]/75" },
  contraband:  { label: "Contraband",  color: "#E4AE39", glow: "shadow-[0_0_36px_#E4AE3970,0_0_80px_#E4AE3920]", border: "border-[#E4AE39]/80" },
};

// ─── Wear config ──────────────────────────────────────────────────────────────
const WEAR_TIERS = [
  { max: 0.07,  label: "FN",  fullLabel: "Factory New",    color: "#22C55E" },
  { max: 0.15,  label: "MW",  fullLabel: "Minimal Wear",   color: "#84CC16" },
  { max: 0.38,  label: "FT",  fullLabel: "Field-Tested",   color: "#EAB308" },
  { max: 0.45,  label: "WW",  fullLabel: "Well-Worn",      color: "#F97316" },
  { max: 1.0,   label: "BS",  fullLabel: "Battle-Scarred", color: "#EF4444" },
];

function getWearTier(float) {
  return WEAR_TIERS.find((t) => float <= t.max) ?? WEAR_TIERS[4];
}

// ─── WearBar ──────────────────────────────────────────────────────────────────
const WearBar = memo(({ float }) => {
  const tier = getWearTier(float);
  const pct = Math.min(float * 100, 100);

  return (
    <div className="space-y-1">
      {/* Labels row */}
      <div className="flex items-center justify-between">
        <span
          className="text-[10px] font-semibold tracking-widest uppercase"
          style={{ color: tier.color }}
        >
          {tier.fullLabel}
        </span>
        <span className="font-mono text-[10px] text-slate-400">
          {float.toFixed(6)}
        </span>
      </div>

      {/* Track */}
      <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-white/5">
        {/* Gradient fill */}
        <div
          className="absolute inset-y-0 left-0 rounded-full transition-all duration-500"
          style={{
            width: `${pct}%`,
            background: `linear-gradient(90deg, #22C55E, #EAB308 50%, #EF4444)`,
          }}
        />
        {/* Float marker */}
        <div
          className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2 rounded-full bg-white shadow-[0_0_4px_#fff]"
          style={{ left: `calc(${pct}% - 1px)` }}
        />
      </div>

      {/* Tier ticks */}
      <div className="flex justify-between px-0.5">
        {WEAR_TIERS.map((t) => (
          <span key={t.label} className="text-[9px] text-slate-600">
            {t.label}
          </span>
        ))}
      </div>
    </div>
  );
});

WearBar.displayName = "WearBar";

// ─── SkinImage ────────────────────────────────────────────────────────────────
// React §3: lazy load + placeholder to prevent CLS
const SkinImage = memo(({ src, alt, rarityColor }) => {
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);

  const handleLoad = useCallback(() => setLoaded(true), []);
  const handleError = useCallback(() => setError(true), []);

  return (
    <div className="relative aspect-[4/3] w-full overflow-hidden rounded-md bg-white/[0.03]">
      {/* Skeleton shimmer */}
      {!loaded && !error && (
        <div className="absolute inset-0 animate-pulse bg-gradient-to-r from-white/5 via-white/10 to-white/5 bg-[length:200%_100%]" />
      )}

      {/* Subtle radial glow behind image */}
      <div
        className="pointer-events-none absolute inset-0 opacity-20"
        style={{
          background: `radial-gradient(ellipse at center, ${rarityColor}44 0%, transparent 70%)`,
        }}
      />

      {error ? (
        <div className="flex h-full items-center justify-center text-slate-600">
          <svg className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
        </div>
      ) : (
        <img
          src={src}
          alt={alt}
          loading="lazy"          // React §3: lazy load off-screen images
          decoding="async"        // React §3: non-blocking decode
          onLoad={handleLoad}
          onError={handleError}
          className={[
            "h-full w-full object-contain p-3 transition-opacity duration-300",
            loaded ? "opacity-100" : "opacity-0",
          ].join(" ")}
        />
      )}
    </div>
  );
});

SkinImage.displayName = "SkinImage";

// ─── SkinCard ─────────────────────────────────────────────────────────────────
// React.memo: перерендер только при изменении пропсов (важно для виртуализованных списков)
const SkinCard = memo(
  ({
    name = "AK-47",
    skin = "Redline",
    float = 0.1423,
    price = 14.5,
    currency = "USD",
    rarity = "classified",
    stattrak = false,
    souvenir = false,
    patternId = null,
    patternLabel = null,
    imageUrl = null,
    onBuy,
    onTrade,
  }) => {
    const r = RARITY[rarity] ?? RARITY.consumer;

    const formattedPrice = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
    }).format(price);

    return (
      <article
        className={[
          "group relative flex flex-col gap-3 rounded-xl border bg-[#13161E] p-3",
          "cursor-pointer select-none",
          "transition-all duration-200 ease-out",
          "hover:-translate-y-0.5 hover:bg-[#161920]",
          r.border,
          r.glow,
        ].join(" ")}
        // Keyboard accessibility
        role="button"
        tabIndex={0}
        aria-label={`${stattrak ? "StatTrak " : ""}${name} | ${skin}, ${getWearTier(float).fullLabel}, ${formattedPrice}`}
      >
        {/* ── Badges row ──────────────────────────────────────── */}
        <div className="flex items-center gap-1.5">
          {/* Rarity badge */}
          <span
            className="rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-widest"
            style={{
              color: r.color,
              background: `${r.color}18`,
              border: `1px solid ${r.color}40`,
            }}
          >
            {r.label}
          </span>

          {/* StatTrak */}
          {stattrak && (
            <span className="rounded border border-[#CF6A32]/50 bg-[#CF6A32]/10 px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-widest text-[#CF6A32]">
              ST™
            </span>
          )}

          {/* Souvenir */}
          {souvenir && (
            <span className="rounded border border-[#FFD700]/50 bg-[#FFD700]/10 px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-widest text-[#FFD700]">
              SV
            </span>
          )}

          {/* Pattern ID */}
          {patternId !== null && (
            <span
              className="ml-auto rounded border px-1.5 py-0.5 font-mono text-[9px] font-semibold"
              style={{
                color: r.color,
                borderColor: `${r.color}40`,
                background: `${r.color}10`,
              }}
            >
              #{patternId}{patternLabel ? ` · ${patternLabel}` : ""}
            </span>
          )}
        </div>

        {/* ── Skin image ──────────────────────────────────────── */}
        <SkinImage
          src={imageUrl}
          alt={`${name} | ${skin}`}
          rarityColor={r.color}
        />

        {/* ── Name ────────────────────────────────────────────── */}
        <div className="space-y-0.5 px-0.5">
          <p className="font-['Rajdhani',sans-serif] text-sm font-semibold leading-tight text-slate-200">
            {name}
          </p>
          <p
            className="font-['Rajdhani',sans-serif] text-sm font-semibold leading-tight"
            style={{ color: r.color }}
          >
            {skin}
          </p>
        </div>

        {/* ── Wear bar ─────────────────────────────────────────── */}
        <div className="px-0.5">
          <WearBar float={float} />
        </div>

        {/* ── Price + Actions ──────────────────────────────────── */}
        <div className="mt-auto flex items-center gap-2 px-0.5">
          <span className="font-['Rajdhani',sans-serif] text-base font-bold text-white">
            {formattedPrice}
          </span>

          <button
            onClick={onTrade}
            className="ml-auto min-h-[36px] rounded-lg border border-white/10 bg-white/5 px-3 text-xs font-semibold text-slate-300 transition-colors hover:border-white/20 hover:bg-white/10 hover:text-white active:scale-95"
            aria-label={`Trade ${name} | ${skin}`}
          >
            Trade
          </button>

          <button
            onClick={onBuy}
            className="min-h-[36px] rounded-lg px-3 text-xs font-bold text-white transition-all active:scale-95"
            style={{
              background: `linear-gradient(135deg, ${r.color}cc, ${r.color}88)`,
              boxShadow: `0 2px 12px ${r.color}40`,
            }}
            aria-label={`Buy ${name} | ${skin} for ${formattedPrice}`}
          >
            Buy
          </button>
        </div>
      </article>
    );
  },
  // Custom comparator: пропускаем перерендер если только внешние данные не изменились
  (prev, next) =>
    prev.float === next.float &&
    prev.price === next.price &&
    prev.rarity === next.rarity &&
    prev.imageUrl === next.imageUrl &&
    prev.stattrak === next.stattrak &&
    prev.souvenir === next.souvenir &&
    prev.patternId === next.patternId
);

SkinCard.displayName = "SkinCard";

export default SkinCard;

// ─── Demo ─────────────────────────────────────────────────────────────────────
export function SkinCardDemo() {
  const skins = [
    { name: "AK-47",    skin: "Redline",          float: 0.142, price: 14.5,   rarity: "classified", imageUrl: "https://community.cloudflare.steamstatic.com/economy/image/-9a81dlWLwJ2UUGcVs_nsVtzdOEdtWwKGZZLQHTxDZ7I56KU0Zwwo4NUX4oFJZEHLbXH5ApeO4YmlhxYQknCRvCo04DEVlxkKgpot7HxfDhjxszJemkV09-5lpKKqPrxN7LEmyVQ7MEpiLuSrYmnjQO3-hBkMWn7d4SRIAFqYV_YxgK-l-_ng5Pu75iB1zI97bhIsvfl0hrpNtbJ/360fx360f" },
    { name: "AWP",      skin: "Dragon Lore",       float: 0.008, price: 1850.0, rarity: "covert",     stattrak: false, patternId: 661, patternLabel: "Blue", imageUrl: "https://community.cloudflare.steamstatic.com/economy/image/-9a81dlWLwJ2UUGcVs_nsVtzdOEdtWwKGZZLQHTxDZ7I56KU0Zwwo4NUX4oFJZEHLbXH5ApeO4YmlhxYQknCRvCo04DEVlxkKgpot621FAR17PLfYQJD_9W7m5S0mvLwOqjummJW4NE_3-qZot-jiVaw-RI-MTz3LYOQcAZoYQzVrla7wu_tg5Pu7Z-LnHdguSh8pA" },
    { name: "Karambit", skin: "Fade",              float: 0.031, price: 620.0,  rarity: "contraband", patternId: 1000, patternLabel: "100%", imageUrl: "https://community.cloudflare.steamstatic.com/economy/image/-9a81dlWLwJ2UUGcVs_nsVtzdOEdtWwKGZZLQHTxDZ7I56KU0Zwwo4NUX4oFJZEHLbXH5ApeO4YmlhxYQknCRvCo04DEVlxkKgpovbSsLQJf2PLacDBA5ciJlY20k_jkI7fUhFRd4fp9i_vG8ML_3FDh_0ZkZj37I4TDIVBvZw7RrFS3xue6h5a8vcuKnCJqsyhy1cbWcQ" },
    { name: "M4A4",     skin: "Howl",              float: 0.43,  price: 2100.0, rarity: "contraband", stattrak: true,  imageUrl: "https://community.cloudflare.steamstatic.com/economy/image/-9a81dlWLwJ2UUGcVs_nsVtzdOEdtWwKGZZLQHTxDZ7I56KU0Zwwo4NUX4oFJZEHLbXH5ApeO4YmlhxYQknCRvCo04DEVlxkKgpou-6kejhjxszFJTwT09S5g4yCmfDLP7LWnn8f6pIl2LyYrNqtjlHg-RI_YDvzd4WRdQ5sZl3T-Ae-wO3og5a4uZ_BnXZquCUpGg" },
    { name: "Desert Eagle", skin: "Blaze",         float: 0.07,  price: 89.0,   rarity: "classified", imageUrl: "https://community.cloudflare.steamstatic.com/economy/image/-9a81dlWLwJ2UUGcVs_nsVtzdOEdtWwKGZZLQHTxDZ7I56KU0Zwwo4NUX4oFJZEHLbXH5ApeO4YmlhxYQknCRvCo04DEVlxkKgposr-1LAtl7PLZTjlH7sSJmIGZnuauZrmIkm5D19V9j-rPyoD8j1yg5UBlZW_6cIeRIFNoN1qG-AO9kuq805W4tJ2YnHpmuCkgs2GbIQv4" },
    { name: "Glock-18", skin: "Gamma Doppler",     float: 0.24,  price: 45.0,   rarity: "covert",     imageUrl: null },
  ];

  return (
    <div className="min-h-screen bg-[#0D0F14] p-8">
      <h2 className="mb-6 font-['Rajdhani',sans-serif] text-2xl font-bold text-slate-100">
        CS2 Skin Hub
      </h2>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        {skins.map((s, i) => (
          <SkinCard
            key={i}
            {...s}
            onBuy={() => console.log("buy", s.name)}
            onTrade={() => console.log("trade", s.name)}
          />
        ))}
      </div>
    </div>
  );
}
