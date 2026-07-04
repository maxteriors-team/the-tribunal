import { describe, expect, it } from "vitest";

import {
  createResourceQueryKeys,
  getResourceInvalidationKeys,
  queryKeys,
} from "./query-keys";

describe("createResourceQueryKeys", () => {
  const keys = createResourceQueryKeys("widgets");

  it("builds the root key for the whole resource across workspaces", () => {
    expect(keys.root()).toEqual(["widgets"]);
  });

  it("builds the workspace-scoped `all` key", () => {
    expect(keys.all("ws_1")).toEqual(["widgets", "ws_1"]);
  });

  it("returns the bare workspace key for an unfiltered list", () => {
    expect(keys.list("ws_1")).toEqual(["widgets", "ws_1"]);
    expect(keys.list("ws_1", undefined)).toEqual(["widgets", "ws_1"]);
    expect(keys.list("ws_1", null)).toEqual(["widgets", "ws_1"]);
  });

  it("appends normalized params for a filtered list", () => {
    expect(keys.list("ws_1", { status: "open", page: 2 })).toEqual([
      "widgets",
      "ws_1",
      { page: 2, status: "open" },
    ]);
  });

  it("treats a params object that is empty after normalization as unfiltered", () => {
    expect(keys.list("ws_1", {})).toEqual(["widgets", "ws_1"]);
    expect(keys.list("ws_1", { ignored: undefined })).toEqual(["widgets", "ws_1"]);
  });

  it("builds detail keys, preserving string and numeric ids", () => {
    expect(keys.detail("ws_1", "abc")).toEqual(["widgets", "ws_1", "abc"]);
    expect(keys.detail("ws_1", 42)).toEqual(["widgets", "ws_1", 42]);
    expect(keys.detail("ws_1", null)).toEqual(["widgets", "ws_1", null]);
    expect(keys.detail("ws_1", undefined)).toEqual(["widgets", "ws_1", undefined]);
  });
});

describe("query-key param normalization", () => {
  const keys = createResourceQueryKeys("widgets");

  it("is order-independent: differently ordered params produce equal keys", () => {
    const a = keys.list("ws_1", { b: 2, a: 1, c: 3 });
    const b = keys.list("ws_1", { c: 3, a: 1, b: 2 });
    expect(a).toEqual(b);
  });

  it("drops only undefined values, keeping null and falsy values", () => {
    expect(keys.list("ws_1", { a: undefined, b: null, c: 0, d: false, e: "" })).toEqual([
      "widgets",
      "ws_1",
      { b: null, c: 0, d: false, e: "" },
    ]);
  });

  it("recursively normalizes nested object params", () => {
    const nested = keys.list("ws_1", {
      outer: { z: 1, a: 2, skip: undefined },
    });
    expect(nested).toEqual([
      "widgets",
      "ws_1",
      { outer: { a: 2, z: 1 } },
    ]);
  });

  it("preserves array order while normalizing array elements", () => {
    const key = keys.list("ws_1", { ids: [{ b: 1, a: 2 }, { d: 3, c: 4 }] });
    expect(key).toEqual([
      "widgets",
      "ws_1",
      { ids: [{ a: 2, b: 1 }, { c: 4, d: 3 }] },
    ]);
  });

  it("produces structurally equal keys for equivalent param objects (cache-hit safe)", () => {
    // React Query compares keys by deep structural equality, so two calls with
    // semantically identical params must yield deeply equal arrays.
    const first = keys.list("ws_1", { search: "acme", page: 1 });
    const second = keys.list("ws_1", { page: 1, search: "acme" });
    expect(first).toStrictEqual(second);
  });
});

describe("getResourceInvalidationKeys", () => {
  it("returns the resource's own `all` key when there are no related resources", () => {
    expect(getResourceInvalidationKeys("tags", "ws_1")).toEqual([["tags", "ws_1"]]);
  });

  it("includes related resource `all` keys after the primary resource", () => {
    expect(getResourceInvalidationKeys("tags", "ws_1", ["contacts"])).toEqual([
      ["tags", "ws_1"],
      ["contacts", "ws_1"],
    ]);
  });

  it("preserves the order of related resources", () => {
    expect(
      getResourceInvalidationKeys("segments", "ws_9", ["contacts", "tags"]),
    ).toEqual([
      ["segments", "ws_9"],
      ["contacts", "ws_9"],
      ["tags", "ws_9"],
    ]);
  });
});

describe("queryKeys factory composition", () => {
  it("spreads the resource builders onto each namespace", () => {
    expect(queryKeys.agents.root()).toEqual(["agents"]);
    expect(queryKeys.agents.all("ws_1")).toEqual(["agents", "ws_1"]);
    expect(queryKeys.agents.detail("ws_1", "a1")).toEqual(["agents", "ws_1", "a1"]);
  });

  it("derives filtered-list helpers from the shared list builder", () => {
    expect(queryKeys.agents.activeOnly("ws_1")).toEqual([
      "agents",
      "ws_1",
      { active_only: true },
    ]);
    expect(queryKeys.phoneNumbers.smsEnabled("ws_1")).toEqual([
      "phone-numbers",
      "ws_1",
      { sms_enabled: true },
    ]);
    expect(queryKeys.phoneNumbers.activeTextCapable("ws_1")).toEqual([
      "phone-numbers",
      "ws_1",
      { active_only: true, text_capable: true },
    ]);
  });

  it("nests detail-scoped sub-resources under the detail key", () => {
    expect(queryKeys.agents.versions("ws_1", "a1")).toEqual([
      "agents",
      "ws_1",
      "a1",
      "versions",
    ]);
    expect(queryKeys.contacts.timeline("ws_1", 7)).toEqual([
      "contacts",
      "ws_1",
      7,
      "timeline",
    ]);
    expect(queryKeys.contacts.timeline("ws_1", 7, 25)).toEqual([
      "contacts",
      "ws_1",
      7,
      "timeline",
      { limit: 25 },
    ]);
    expect(queryKeys.contacts.companycamPhotos("ws_1", 7)).toEqual([
      "contacts",
      "ws_1",
      7,
      "companycam-photos",
    ]);
    expect(queryKeys.contacts.attachments("ws_1", 7)).toEqual([
      "contacts",
      "ws_1",
      7,
      "attachments",
    ]);
  });

  it("nests job costing sub-resources under the job detail key", () => {
    const detail = queryKeys.jobs.detail("ws_1", "job_1");
    expect(queryKeys.jobs.timeEntries("ws_1", "job_1")).toEqual([
      ...detail,
      "time-entries",
    ]);
    expect(queryKeys.jobs.expenses("ws_1", "job_1")).toEqual([...detail, "expenses"]);
    expect(queryKeys.jobs.profitability("ws_1", "job_1")).toEqual([
      ...detail,
      "profitability",
    ]);
  });

  it("builds reporting keys, defaulting the optional as-of/params slot to null", () => {
    expect(queryKeys.reports.arAging("ws_1")).toEqual([
      "reports",
      "ws_1",
      "ar-aging",
      null,
    ]);
    expect(queryKeys.reports.arAging("ws_1", "2026-07-01")).toEqual([
      "reports",
      "ws_1",
      "ar-aging",
      "2026-07-01",
    ]);
    expect(queryKeys.reports.jobPnl("ws_1")).toEqual([
      "reports",
      "ws_1",
      "job-pnl",
      undefined,
    ]);
    expect(
      queryKeys.reports.jobPnl("ws_1", { date_from: "2026-06-01", date_to: undefined }),
    ).toEqual(["reports", "ws_1", "job-pnl", { date_from: "2026-06-01" }]);
  });

  it("nests stat keys under the workspace `all` key so a broad invalidate clears them", () => {
    const all = queryKeys.appointments.all("ws_1");
    const stats = queryKeys.appointments.stats("ws_1");
    expect(stats).toEqual([...all, "stats"]);
    expect(stats.slice(0, all.length)).toEqual([...all]);
  });

  it("derives contact filtered lists from `all` so cache invalidation cascades", () => {
    const all = queryKeys.appointments.all("ws_1");
    const byContact = queryKeys.appointments.byContact("ws_1", 5);
    expect(byContact).toEqual(["appointments", "ws_1", { contact_id: 5 }]);
    expect(byContact.slice(0, all.length)).toEqual([...all]);
  });

  it("builds the bespoke proposal-template + public-proposal keys with a stable shape", () => {
    // These drive cache invalidation across the settings tab, the public
    // proposal page, and the quotes-list link actions, so their shape is a
    // contract. `publicProposals` mirrors the `publicReviews` namespace.
    expect(queryKeys.proposalTemplate.settings("ws_1")).toEqual([
      "proposal-template",
      "ws_1",
    ]);
    expect(queryKeys.publicProposals.all()).toEqual(["public-proposals"]);
    expect(queryKeys.publicProposals.byToken("tok_abc")).toEqual([
      "public-proposals",
      "tok_abc",
    ]);
  });

  it("normalizes infinite-contacts filters and prefixes with the contacts root", () => {
    expect(
      queryKeys.contacts.infinite("ws_1", { status: "lead", search: undefined }),
    ).toEqual(["contacts", "ws_1", "infinite", { status: "lead" }]);
    expect(queryKeys.contacts.infinite(null, {})).toEqual([
      "contacts",
      null,
      "infinite",
      undefined,
    ]);
  });
});
