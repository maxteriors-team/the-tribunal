# CRM WCAG 2.2 AA remediation plan

## Scope and design read

- **Surface:** dense authenticated CRM dashboard, plus customer proposal/embed surfaces.
- **Audience:** operators using desktop, touch/mobile, keyboard, zoom, and assistive technology.
- **Primary job:** keep every existing CRM workflow operable and understandable without changing its visual hierarchy.
- **Risk:** inaccessible names and labels hide controls from screen readers; mouse-only scroll/step controls block keyboard users; low-contrast financial text can hide decision-critical values.
- **Direction:** preserve the current shadcn/Radix/Tailwind system and visible layout; add semantic names, associations, focusability, state announcements, and AA-safe semantic colors at the nearest reusable component or usage site.

## Steps

1. **Control semantics**
   - Give icon-only buttons, selects, mobile Settings tabs, switches, steppers, quantity inputs/buttons, progress bars, and proposal/carousel navigation descriptive accessible names.
   - Add `aria-current`, `aria-pressed`, or value text where state matters; hide decorative icons from the accessibility tree.
   - Replace filter-only Radix tabs that point at nonexistent tab panels with pressed-button groups.

2. **Forms and scrolling**
   - Link visible labels to proposal, seasonal/permanent pricing, embed configuration, and share-link controls using stable IDs and `htmlFor`; provide distinct names where one visual label covers multiple controls.
   - Make intentionally scrollable report/dashboard/code regions keyboard-focusable and named, with existing focus-visible styling retained.

3. **Contrast and route-specific fixes**
   - Replace failing report/financial status colors with measured light/dark variants that meet 4.5:1 for normal text.
   - Fix empty combobox names and other serious/critical axe findings on the audited CRM creation, filtering, review, and Settings routes without redesigning the UI.

4. **Regression coverage**
   - Add `@axe-core/playwright` and an accessibility E2E suite covering representative affected authenticated routes at desktop and mobile viewports, failing on applicable WCAG 2.2 A/AA serious or critical violations.
   - Add keyboard-only Playwright assertions for tabs, steppers, icon controls, scroll regions, quantity controls, progress state, and public controls; document the short manual keyboard/zoom/screen-reader smoke matrix where human judgment is still required.
   - Add focused component tests where a shared primitive or dynamic label is easier to prove deterministically.

5. **Evidence and release notes**
   - Update `frontend/DESIGN.md` and the existing focused `COMPLIANCE.md` register without claiming product-wide conformance.
   - Run formatting/type/lint/focused tests, then the accessibility Playwright suite against the available local stack; capture representative desktop/mobile screenshots and record anything that remains manually unverified.

## Completion gate

- Targeted lint/type/tests pass.
- Axe coverage finds no serious/critical violations in the scoped rendered routes.
- Keyboard checks prove visible focus and operation for the listed controls at desktop and mobile widths.
- Existing unrelated dirty work remains intact.
