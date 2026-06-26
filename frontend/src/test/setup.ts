import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { vi, afterAll, afterEach, beforeAll } from "vitest";

import { server } from "@/test/msw/server";

// MSW lifecycle — start once, reset handlers between tests, close at teardown.
// `onUnhandledRequest: "error"` makes accidental network calls a loud test
// failure instead of a silent timeout. Override per-test with `server.use(...)`.
beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterAll(() => {
  server.close();
});

// Tell React we're inside an act() environment so state updates triggered
// outside React (e.g. userEvent.click before async resolution) don't warn.
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Clean up the DOM and any per-test MSW handler overrides between tests.
afterEach(() => {
  cleanup();
  server.resetHandlers();
});

// Mock next/navigation — App Router hooks throw outside a Next runtime.
const mockRouter = {
  push: vi.fn(),
  replace: vi.fn(),
  back: vi.fn(),
  forward: vi.fn(),
  refresh: vi.fn(),
  prefetch: vi.fn(),
};

vi.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}));

// jsdom doesn't implement matchMedia — many UI libs probe it on mount.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  configurable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// jsdom doesn't implement IntersectionObserver — virtualized lists/menus need it.
class MockIntersectionObserver implements IntersectionObserver {
  readonly root: Element | Document | null = null;
  readonly rootMargin: string = "";
  readonly thresholds: ReadonlyArray<number> = [];
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  takeRecords = vi.fn(() => []);
}

Object.defineProperty(window, "IntersectionObserver", {
  writable: true,
  configurable: true,
  value: MockIntersectionObserver,
});
Object.defineProperty(globalThis, "IntersectionObserver", {
  writable: true,
  configurable: true,
  value: MockIntersectionObserver,
});

// ResizeObserver — Radix and other UI libs need it in jsdom.
class MockResizeObserver {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}

Object.defineProperty(window, "ResizeObserver", {
  writable: true,
  configurable: true,
  value: MockResizeObserver,
});
Object.defineProperty(globalThis, "ResizeObserver", {
  writable: true,
  configurable: true,
  value: MockResizeObserver,
});

// jsdom lacks the pointer-capture and scrollIntoView APIs that Radix
// Select/Popover call when a trigger is activated. Without these, opening a
// Radix Select via userEvent throws. Stub them so option pickers are testable.
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = vi.fn(() => false);
}
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = vi.fn();
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = vi.fn();
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn();
}
