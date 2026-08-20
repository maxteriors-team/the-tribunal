const HTTP_PROTOCOLS = new Set(["http:", "https:"]);

export const EMBED_PARENT_ORIGIN_HEADER = "X-Embed-Parent-Origin";

function normalizeHttpOrigin(value: string | null | undefined): string | null {
  if (!value) return null;

  try {
    const url = new URL(value);
    return HTTP_PROTOCOLS.has(url.protocol) ? url.origin : null;
  } catch {
    return null;
  }
}

/**
 * Resolve the browser-attested origin hosting this embed.
 *
 * `ancestorOrigins` and `document.referrer` are populated by the browser, so an
 * embedding page cannot override them through iframe query parameters. If a
 * framed browser withholds both values, requests fail closed without the
 * parent-origin header instead of falling back to our own iframe origin.
 */
export function getEmbedParentOrigin(
  win: Window = window,
  doc: Document = document,
): string | null {
  if (win.parent === win) {
    return normalizeHttpOrigin(win.location.origin);
  }

  const nearestAncestor = win.location.ancestorOrigins?.item(0);
  return normalizeHttpOrigin(nearestAncestor) ?? normalizeHttpOrigin(doc.referrer);
}

/** Add the verified parent claim to a same-origin public embed API request. */
export function getEmbedRequestHeaders(
  initialHeaders?: HeadersInit,
  win: Window = window,
  doc: Document = document,
): Headers {
  const headers = new Headers(initialHeaders);
  const parentOrigin = getEmbedParentOrigin(win, doc);
  if (parentOrigin) {
    headers.set(EMBED_PARENT_ORIGIN_HEADER, parentOrigin);
  }
  return headers;
}

/** Public embed fetch wrapper that preserves caller headers and adds parent context. */
export function embedFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  return fetch(input, {
    ...init,
    headers: getEmbedRequestHeaders(init.headers),
  });
}
