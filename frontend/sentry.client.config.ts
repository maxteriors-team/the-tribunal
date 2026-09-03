// Sentry client-side initialization.
// Runs in the browser when a user loads any page.
// https://docs.sentry.io/platforms/javascript/guides/nextjs/

import * as Sentry from "@sentry/nextjs";

const INTAKE_CAPABILITY_PATTERNS = [/#token=[A-Za-z0-9_-]+/gi, /%23token%3D[A-Za-z0-9_-]+/gi];

function scrubIntakeCapability(value: string | undefined): string | undefined {
  if (!value) return value;
  return INTAKE_CAPABILITY_PATTERNS.reduce(
    (scrubbed, pattern) => scrubbed.replace(pattern, "#token=[Filtered]"),
    value,
  );
}

function scrubBreadcrumbData(
  data: Record<string, unknown> | undefined,
): Record<string, unknown> | undefined {
  if (!data) return data;
  return Object.fromEntries(
    Object.entries(data).map(([key, value]) => [
      key,
      typeof value === "string" ? scrubIntakeCapability(value) : value,
    ]),
  );
}

function scrubRequestHeaders(
  headers: Record<string, string> | undefined,
): Record<string, string> | undefined {
  if (!headers) return headers;
  return Object.fromEntries(
    Object.entries(headers).map(([key, value]) => [
      key,
      key.toLowerCase() === "authorization"
        ? "[REDACTED]"
        : (scrubIntakeCapability(value) ?? value),
    ]),
  );
}

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.VERCEL_ENV,
  tracesSampleRate: 0.1,
  beforeBreadcrumb(breadcrumb) {
    return {
      ...breadcrumb,
      message: scrubIntakeCapability(breadcrumb.message),
      data: scrubBreadcrumbData(breadcrumb.data),
    };
  },
  beforeSend(event) {
    if (event.request?.url) event.request.url = scrubIntakeCapability(event.request.url);
    if (event.request) event.request.headers = scrubRequestHeaders(event.request.headers);
    if (event.transaction) event.transaction = scrubIntakeCapability(event.transaction);
    if (event.breadcrumbs) {
      event.breadcrumbs = event.breadcrumbs.map((breadcrumb) => ({
        ...breadcrumb,
        message: scrubIntakeCapability(breadcrumb.message),
        data: scrubBreadcrumbData(breadcrumb.data),
      }));
    }
    return event;
  },
});

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
