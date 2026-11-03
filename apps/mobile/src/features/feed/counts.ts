/**
 * A count, in as few characters as it can be read in.
 *
 * **Thousands, not digits.** "1.6K" and "1,632" change nothing about
 * what anybody does with the number, and the first does not push the
 * controls beside it along a row that is already tight. Under a
 * thousand the exact figure is short enough to keep.
 *
 * One decimal below ten thousand, none above: "9.7K" is a real
 * difference from "9.2K", and "47.3K" is noise.
 */
export function compactCount(count: number): string {
  if (count < 1000) return String(count);
  if (count < 10_000) {
    const tenths = Math.floor(count / 100) / 10;
    return `${tenths % 1 === 0 ? tenths.toFixed(0) : tenths.toFixed(1)}K`;
  }
  if (count < 1_000_000) return `${Math.floor(count / 1000)}K`;
  const millions = Math.floor(count / 100_000) / 10;
  return `${millions % 1 === 0 ? millions.toFixed(0) : millions.toFixed(1)}M`;
}
