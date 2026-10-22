// Peso display (2026-10-22): the full amount with comma separators and two
// decimals (₱1,500,000.00), never abbreviated (₱1.2M / ₱500K). Display only --
// values are never rounded before they are used in a calculation.
const PESO = new Intl.NumberFormat("en-PH", {
  style: "currency",
  currency: "PHP",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatPeso(value: number | null | undefined): string {
  return value == null || Number.isNaN(value) ? "—" : PESO.format(value);
}

// Sums peso amounts in whole centavos so a long column of values like 0.1 +
// 0.2 doesn't drift (floating-point) before it is displayed.
export function sumPesos(values: (number | null | undefined)[]): number {
  return values.reduce<number>((cents, v) => cents + Math.round((v ?? 0) * 100), 0) / 100;
}
