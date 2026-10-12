import agrisureLogo from "@/assets/agrisuregis-logo.png";

// App logo mark (2026-10-12): the official AgriSureGIS logo
// (docs/AgriSureGIS LOGO.png, trimmed copy in src/assets), replacing the
// earlier inline-SVG shield. `size` is the height; width follows the logo's
// own aspect ratio (256x211), so it isn't squashed into a square.
export function BrandLogo({ size = 32, className = "" }: { size?: number; className?: string }) {
  return (
    <img
      src={agrisureLogo}
      alt="AgriSureGIS logo"
      style={{ height: size, width: "auto" }}
      className={className}
    />
  );
}
