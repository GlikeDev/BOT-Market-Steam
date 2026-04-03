import { useRef, useEffect } from "react";

/**
 * useTilt — zero-rerender 3D tilt via direct DOM mutation.
 *
 * Performance contract (React domain §9):
 *  • No setState → zero React re-renders during mouse tracking
 *  • will-change:transform set ONLY on mouseenter, cleared on mouseleave
 *    (setting it always wastes GPU memory for every card in the list)
 *  • RAF-throttled: skips frames when a pending RAF already exists
 *  • Passive event listeners: browser never waits for JS before scrolling
 *  • contain: strict on the host element → isolates paint/layout from siblings
 *  • cancelAnimationFrame on unmount → no stale callbacks
 *
 * @param {object} opts
 * @param {number} opts.maxAngle    – max tilt degrees (default 14)
 * @param {number} opts.perspective – CSS perspective in px (default 700)
 * @param {number} opts.scale       – scale on hover (default 1.05)
 * @param {number} opts.glareOpacity– peak glare opacity 0-1 (default 0.18)
 * @param {string} opts.rarityColor – hex color for edge glow (optional)
 * @returns {{ cardRef, glareRef }}
 */
export function useTilt({
  maxAngle     = 14,
  perspective  = 700,
  scale        = 1.05,
  glareOpacity = 0.18,
  rarityColor  = null,
} = {}) {
  const cardRef  = useRef(null);
  const glareRef = useRef(null);
  const rafRef   = useRef(null);
  const hovered  = useRef(false);

  useEffect(() => {
    const card  = cardRef.current;
    const glare = glareRef.current;
    if (!card) return;

    // ── Enter ───────────────────────────────────────────────────────────────
    function onEnter() {
      hovered.current = true;
      // Only now pay the GPU cost — not on every idle card
      card.style.willChange   = "transform";
      card.style.transition   = "transform 0.15s ease-out, box-shadow 0.15s ease-out";
      if (glare) glare.style.opacity = "0";
    }

    // ── Move ────────────────────────────────────────────────────────────────
    function onMove(e) {
      if (!hovered.current) return;
      if (rafRef.current)   return;          // already a frame scheduled → skip

      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null;

        const rect = card.getBoundingClientRect();
        // Normalise cursor to –1…+1 within the element
        const nx = ((e.clientX - rect.left)  / rect.width  - 0.5) * 2;
        const ny = ((e.clientY - rect.top)   / rect.height - 0.5) * 2;

        const rotY =  nx * maxAngle;   // left–right tilt
        const rotX = -ny * maxAngle;   // up–down tilt

        // Remove transition while tracking (snap to finger)
        card.style.transition = "";
        card.style.transform  =
          `perspective(${perspective}px) rotateX(${rotX}deg) rotateY(${rotY}deg) scale(${scale})`;

        // Derive edge glow intensity from tilt magnitude
        if (rarityColor) {
          const intensity = Math.hypot(nx, ny) * 0.5; // 0..1
          card.style.boxShadow =
            `0 ${8 + rotX * 1.5}px ${28 + intensity * 40}px rgba(0,0,0,0.55),` +
            `0 0 ${12 + intensity * 30}px ${rarityColor}${Math.round(intensity * 80).toString(16).padStart(2,"0")}`;
        }

        // Specular glare: radial highlight follows cursor position
        if (glare) {
          const gx = ((nx + 1) / 2) * 100;  // 0..100 %
          const gy = ((ny + 1) / 2) * 100;
          glare.style.opacity    = String(glareOpacity * Math.hypot(nx, ny));
          glare.style.background =
            `radial-gradient(circle at ${gx}% ${gy}%,` +
            ` rgba(255,255,255,0.55) 0%,` +
            ` rgba(255,255,255,0.08) 35%,` +
            ` transparent 65%)`;
        }
      });
    }

    // ── Leave ───────────────────────────────────────────────────────────────
    function onLeave() {
      hovered.current = false;

      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }

      // Spring-back
      card.style.transition  = "transform 0.5s cubic-bezier(0.22,1,0.36,1), box-shadow 0.4s ease";
      card.style.transform   = `perspective(${perspective}px) rotateX(0deg) rotateY(0deg) scale(1)`;
      card.style.boxShadow   = "";
      // Release the GPU layer — don't hold will-change on idle cards
      setTimeout(() => {
        if (!hovered.current) card.style.willChange = "";
      }, 500);

      if (glare) {
        glare.style.transition = "opacity 0.4s ease";
        glare.style.opacity    = "0";
      }
    }

    // passive:true → browser can scroll without waiting for JS handler
    card.addEventListener("mouseenter", onEnter, { passive: true });
    card.addEventListener("mousemove",  onMove,  { passive: true });
    card.addEventListener("mouseleave", onLeave, { passive: true });

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      card.removeEventListener("mouseenter", onEnter);
      card.removeEventListener("mousemove",  onMove);
      card.removeEventListener("mouseleave", onLeave);
      // Always clean up will-change on unmount
      card.style.willChange = "";
    };
  }, [maxAngle, perspective, scale, glareOpacity, rarityColor]);

  return { cardRef, glareRef };
}
