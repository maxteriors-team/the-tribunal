/**
 * Stable-key helpers shared by the pricing editors.
 *
 * Two different kinds of identifier show up in every one of these editors and
 * must not be confused:
 *
 * * `cid()` — a throwaway client id used only as a React list key, so reordering
 *   or renaming a row never re-mounts the wrong input.
 * * `slugify()` + `uniqueKey()` — the *backend* key, assigned once when a new row
 *   is first saved and frozen thereafter. Saved quotes, shared comparison links,
 *   and the pricing engine all look selections up by that key, so re-deriving it
 *   from a renamed label would silently orphan them.
 */

export const cid = (): string =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `cid-${Math.random().toString(36).slice(2)}`;

export function slugify(value: string, fallback: string): string {
  const slug = value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug || fallback;
}

/** Ensure a unique key within an already-used set (append -2, -3, …). */
export function uniqueKey(base: string, used: Set<string>): string {
  let candidate = base;
  let n = 2;
  while (used.has(candidate)) {
    candidate = `${base}-${n}`;
    n += 1;
  }
  used.add(candidate);
  return candidate;
}
