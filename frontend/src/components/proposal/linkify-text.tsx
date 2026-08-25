import type { ReactNode } from "react";

import { canonicalizeTermsUrl } from "@/lib/legal";

/**
 * Render operator-authored plain text with clickable links.
 *
 * Shared by the client proposal footer and the plain-quote footer so an
 * operator can drop a "Terms & Conditions" line (linking to the business
 * website) into Settings > Proposals > Footer and have it render as a real
 * link on every proposal, regardless of which client view a quote uses.
 *
 * Only `http(s)://` URLs are linkified, via string splitting rather than
 * `dangerouslySetInnerHTML`, so stored copy can never inject markup or a
 * `javascript:` URI. Trailing sentence punctuation (e.g. a period ending the
 * line) is kept out of the href so the link still resolves.
 */
export function renderTextWithLinks(text: string): ReactNode[] {
  // Capturing group keeps the URLs in the split output (at odd indices); the
  // regex test below re-identifies them so we don't depend on that position.
  return text.split(/(https?:\/\/[^\s<]+)/g).map((part, index) => {
    if (!/^https?:\/\//.test(part)) {
      return part;
    }
    const trailing = part.match(/[.,;:!?)\]}'"]+$/)?.[0] ?? "";
    const href = trailing ? part.slice(0, -trailing.length) : part;
    const canonicalHref = canonicalizeTermsUrl(href);
    return (
      <span key={index}>
        <a href={canonicalHref} target="_blank" rel="noopener noreferrer">
          {canonicalHref}
        </a>
        {trailing}
      </span>
    );
  });
}
