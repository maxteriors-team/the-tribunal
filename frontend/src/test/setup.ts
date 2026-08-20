import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, vi } from "vitest";

import { server } from "@/test/msw/server";

// MSW lifecycle — start once, reset handlers between tests, close at teardown.
// `onUnhandledRequest: "error"` makes accidental network calls a loud test
// failure instead of a silent timeout. Override per-test with `server.use(...)`.
const unhandledRequests: string[] = [];
const reactActWarnings: string[] = [];
const originalConsoleError = console.error;
const reactActWarningPatterns = [
  "not wrapped in act",
  "A component suspended inside an `act` scope",
  "A suspended resource finished loading inside a test",
];

console.error = (...args: unknown[]) => {
  const message = args.map(String).join(" ");
  if (reactActWarningPatterns.some((pattern) => message.includes(pattern))) {
    reactActWarnings.push(message);
  }
  originalConsoleError(...args);
};

server.events.on("request:unhandled", ({ request }) => {
  unhandledRequests.push(`${request.method} ${request.url}`);
});

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

beforeEach(() => {
  unhandledRequests.length = 0;
  reactActWarnings.length = 0;
});

afterAll(() => {
  server.close();
  console.error = originalConsoleError;
});

// Tell React to report updates that escape Testing Library's act() boundary.
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Clean up the DOM and any per-test MSW handler overrides between tests.
afterEach(() => {
  cleanup();
  server.resetHandlers();
  const failures = [
    ...(unhandledRequests.length > 0
      ? [`Unhandled MSW request(s):\n${unhandledRequests.join("\n")}`]
      : []),
    ...(reactActWarnings.length > 0
      ? [`React act warning(s):\n${reactActWarnings.join("\n")}`]
      : []),
  ];
  if (failures.length > 0) throw new Error(failures.join("\n\n"));
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

// Mock next/font — the loaders are build-time transforms and are undefined at
// runtime outside a Next build, so any component that ships its own fonts (the
// client proposal page, the sales wizard) fails to even import. Returns the
// same className/variable shape the real loaders do.
const mockFont = () => ({
  className: "mock-font",
  variable: "mock-font-variable",
  style: { fontFamily: "mock-font" },
});
// Vitest validates named exports against the mock, so each loader the app uses
// is listed here; add a font here when a component starts importing one.
vi.mock("next/font/google", () => ({
  Cormorant_Garamond: mockFont,
  Inter: mockFont,
  Manrope: mockFont,
  Montserrat: mockFont,
}));
vi.mock("next/font/local", () => ({ default: mockFont }));

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

// Browser rendering APIs that jsdom intentionally leaves unimplemented.
Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
  configurable: true,
  writable: true,
  value: vi.fn(() => null),
});
window.scrollTo = vi.fn();
