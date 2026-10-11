import { useId } from "react";

// App logo mark (2026-10-11): a crop-insurance shield holding a rice stalk
// above field furrows -- shield for the insurance, rice for the insured
// crop, furrows for the mapped farm land. Gold matches the header's
// active-tab underline (#fbbf24). Inline SVG, so it stays sharp at any size
// and needs no image asset.
export function BrandLogo({ size = 32, className = "" }: { size?: number; className?: string }) {
  // Unique per instance, so two logos on one page don't share gradient ids.
  const gradientId = `brand-shield-${useId().replace(/:/g, "")}`;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      className={className}
      role="img"
      aria-label="PCIC-GIS logo"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#22c55e" />
          <stop offset="100%" stopColor="#14532d" />
        </linearGradient>
      </defs>

      {/* Shield */}
      <path
        d="M16 2.5 L27 6.5 V15 C27 22 22.2 27.4 16 29.5 C9.8 27.4 5 22 5 15 V6.5 Z"
        fill={`url(#${gradientId})`}
        stroke="#fbbf24"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />

      {/* Field furrows */}
      <path d="M9.5 22.5 Q16 20 22.5 22.5" fill="none" stroke="#fbbf24" strokeWidth="1.1" strokeLinecap="round" />
      <path d="M11.5 25.5 Q16 23.8 20.5 25.5" fill="none" stroke="#fbbf24" strokeWidth="1.1" strokeLinecap="round" opacity="0.7" />

      {/* Rice stalk: stem, leaf, grains */}
      <path d="M16 21.5 C16 17 16.5 12.5 18.5 8.5" fill="none" stroke="#ffffff" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M16 20.5 C13.6 20.2 11.7 18.7 10.8 16.6 C13.2 16.8 15.1 18.3 16 20.5 Z" fill="#ffffff" opacity="0.85" />
      <ellipse cx="18.9" cy="7.6" rx="1.2" ry="2.1" transform="rotate(25 18.9 7.6)" fill="#ffffff" />
      <ellipse cx="16.1" cy="11.1" rx="1.2" ry="2.1" transform="rotate(-35 16.1 11.1)" fill="#ffffff" />
      <ellipse cx="19.6" cy="12.2" rx="1.2" ry="2.1" transform="rotate(40 19.6 12.2)" fill="#ffffff" />
      <ellipse cx="15.5" cy="15.2" rx="1.2" ry="2.1" transform="rotate(-40 15.5 15.2)" fill="#ffffff" />
      <ellipse cx="19" cy="16.2" rx="1.2" ry="2.1" transform="rotate(45 19 16.2)" fill="#ffffff" />
    </svg>
  );
}
