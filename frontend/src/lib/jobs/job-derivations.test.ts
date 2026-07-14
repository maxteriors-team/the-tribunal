import { describe, expect, it } from "vitest";

import type { Job } from "@/lib/api/jobs";

import {
  buildJobsQueryParams,
  formatJobSiteAddress,
  formatLineItemQuantity,
  isoToLocalInput,
  jobSiteAddressLines,
  jobSiteMapsUrl,
  jobSiteShortLine,
  jobStatusLabel,
  jobWindowError,
  jobsForDay,
  localToIso,
  technicianInitials,
  unscheduledJobs,
  type JobSite,
} from "./job-derivations";

function makeSite(overrides: Partial<JobSite> = {}): JobSite {
  return {
    id: "site-1",
    name: "Helen Vasquez residence",
    address_line1: "4412 Ridgeview Dr",
    address_line2: null,
    city: "Austin",
    state: "TX",
    postal_code: "78731",
    country: "US",
    access_notes: null,
    latitude: null,
    longitude: null,
    ...overrides,
  };
}

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    workspace_id: "ws-1",
    contact_id: 1,
    service_location_id: null,
    crew_id: null,
    title: "Fix HVAC",
    description: null,
    status: "scheduled",
    scheduled_start: "2026-05-20T15:00:00.000Z",
    scheduled_end: "2026-05-20T17:00:00.000Z",
    external_source: null,
    external_id: null,
    technicians: [],
    created_at: "2026-05-01T00:00:00.000Z",
    updated_at: "2026-05-01T00:00:00.000Z",
    ...overrides,
  };
}

describe("jobsForDay", () => {
  it("keeps jobs whose scheduled start is on the day", () => {
    const day = new Date("2026-05-20T18:00:00.000Z");
    const onDay = makeJob({ id: "a", scheduled_start: "2026-05-20T15:00:00.000Z" });
    const otherDay = makeJob({ id: "b", scheduled_start: "2026-05-21T15:00:00.000Z" });
    const result = jobsForDay([onDay, otherDay], day);
    expect(result.map((job) => job.id)).toEqual(["a"]);
  });

  it("excludes unscheduled jobs", () => {
    const day = new Date("2026-05-20T18:00:00.000Z");
    const queued = makeJob({ id: "c", scheduled_start: null });
    expect(jobsForDay([queued], day)).toEqual([]);
  });
});

describe("unscheduledJobs", () => {
  it("returns only jobs without a time window", () => {
    const scheduled = makeJob({ id: "a", scheduled_start: "2026-05-20T15:00:00.000Z" });
    const queued = makeJob({ id: "b", scheduled_start: null });
    expect(unscheduledJobs([scheduled, queued]).map((job) => job.id)).toEqual(["b"]);
  });
});

describe("technicianInitials", () => {
  it("combines first and last initials uppercased", () => {
    expect(technicianInitials("Ada Lovelace")).toBe("AL");
  });

  it("uses a single initial for one-word names", () => {
    expect(technicianInitials("Cher")).toBe("C");
  });

  it("falls back to ? for empty input", () => {
    expect(technicianInitials("")).toBe("?");
  });
});

describe("jobStatusLabel", () => {
  it("maps a status value to its human label", () => {
    expect(jobStatusLabel("in_progress")).toBe("In progress");
  });
});

describe("jobWindowError", () => {
  it("accepts an empty window (queued job)", () => {
    expect(jobWindowError("", "")).toBe("");
  });

  it("rejects a half-set window", () => {
    expect(jobWindowError("2026-05-20T15:00", "")).not.toBe("");
    expect(jobWindowError("", "2026-05-20T17:00")).not.toBe("");
  });

  it("rejects an end at or before the start", () => {
    expect(jobWindowError("2026-05-20T17:00", "2026-05-20T15:00")).not.toBe("");
    expect(jobWindowError("2026-05-20T17:00", "2026-05-20T17:00")).not.toBe("");
  });

  it("accepts a well-ordered window", () => {
    expect(jobWindowError("2026-05-20T15:00", "2026-05-20T17:00")).toBe("");
  });
});

describe("localToIso / isoToLocalInput", () => {
  it("maps an empty input to null and null to an empty string", () => {
    expect(localToIso("")).toBeNull();
    expect(isoToLocalInput(null)).toBe("");
  });

  it("round-trips an ISO instant through the local input value", () => {
    const iso = "2026-05-20T15:00:00.000Z";
    expect(localToIso(isoToLocalInput(iso))).toBe(iso);
  });

  it("produces a minute-precision local value", () => {
    expect(isoToLocalInput("2026-05-20T15:00:00.000Z")).toHaveLength(16);
  });
});

describe("jobSiteAddressLines", () => {
  it("splits the site into street, unit and city/state/zip lines", () => {
    expect(jobSiteAddressLines(makeSite({ address_line2: "Unit B" }))).toEqual([
      "4412 Ridgeview Dr",
      "Unit B",
      "Austin, TX 78731",
    ]);
  });

  it("drops missing parts instead of emitting stray separators", () => {
    expect(
      jobSiteAddressLines(makeSite({ address_line1: null, state: null, postal_code: null })),
    ).toEqual(["Austin"]);
    expect(formatJobSiteAddress(makeSite({ city: null, state: null, postal_code: null }))).toBe(
      "4412 Ridgeview Dr",
    );
  });

  it("keeps a non-US country and omits the implied US one", () => {
    expect(jobSiteAddressLines(makeSite({ country: "CA" }))).toContain("CA");
    expect(jobSiteAddressLines(makeSite())).not.toContain("US");
  });

  it("treats a missing site as no address at all", () => {
    expect(jobSiteAddressLines(null)).toEqual([]);
    expect(formatJobSiteAddress(undefined)).toBe("");
    expect(jobSiteShortLine(null)).toBe("");
  });

  it("falls back from street to city to site name for the short line", () => {
    expect(jobSiteShortLine(makeSite())).toBe("4412 Ridgeview Dr");
    expect(jobSiteShortLine(makeSite({ address_line1: null }))).toBe("Austin");
    expect(jobSiteShortLine(makeSite({ address_line1: null, city: null }))).toBe(
      "Helen Vasquez residence",
    );
  });
});

describe("jobSiteMapsUrl", () => {
  it("prefers the map pin so a bad address still routes", () => {
    expect(jobSiteMapsUrl(makeSite({ latitude: 30.35, longitude: -97.77 }))).toBe(
      "https://maps.google.com/?q=30.35,-97.77",
    );
  });

  it("falls back to the URL-encoded address", () => {
    expect(jobSiteMapsUrl(makeSite())).toBe(
      "https://maps.google.com/?q=4412%20Ridgeview%20Dr%2C%20Austin%2C%20TX%2078731",
    );
  });

  it("returns null when there is nothing to navigate to", () => {
    expect(jobSiteMapsUrl(null)).toBeNull();
    expect(
      jobSiteMapsUrl(makeSite({ address_line1: null, city: null, state: null, postal_code: null })),
    ).toBeNull();
  });
});

describe("formatLineItemQuantity", () => {
  it("drops the trailing zeros the API sends on whole quantities", () => {
    expect(formatLineItemQuantity(1)).toBe("1");
    expect(formatLineItemQuantity(2.0)).toBe("2");
    expect(formatLineItemQuantity(2.5)).toBe("2.5");
  });

  it("never renders NaN at a technician", () => {
    expect(formatLineItemQuantity(Number.NaN)).toBe("—");
  });
});

describe("buildJobsQueryParams", () => {
  it("includes the week window and omits an empty status filter", () => {
    const params = buildJobsQueryParams("2026-05-18T00:00:00.000Z", "2026-05-24T23:59:59.000Z", "");
    expect(params).toEqual({
      date_from: "2026-05-18T00:00:00.000Z",
      date_to: "2026-05-24T23:59:59.000Z",
    });
  });

  it("adds the status when a filter is selected", () => {
    const params = buildJobsQueryParams("a", "b", "completed");
    expect(params.status).toBe("completed");
  });

  it("adds business_location_id when a location is selected and omits it otherwise", () => {
    expect(buildJobsQueryParams("a", "b", "").business_location_id).toBeUndefined();
    const params = buildJobsQueryParams("a", "b", "", "loc-123");
    expect(params.business_location_id).toBe("loc-123");
  });
});
