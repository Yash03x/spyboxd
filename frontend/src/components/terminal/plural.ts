/**
 * "1 watches", "1 days", "1 films": the product's numbers are the product, and
 * a count that disagrees with its own noun reads as a rounding error in a UI
 * whose whole argument is that every figure is exact. One helper, because the
 * inline ternary was being rewritten at every call site and kept being
 * forgotten at the next one.
 */
export function count(value: number, singular: string, plural?: string): string {
  return `${value.toLocaleString()} ${value === 1 ? singular : (plural ?? `${singular}s`)}`;
}
