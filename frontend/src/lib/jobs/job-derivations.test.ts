import { describe, expect, it } from "vitest";

import type { Job } from "@/lib/api/jobs";

import {
  buildJobsQueryParams,
  isoToLocalInput,
  jobStatusLabel,
  jobWindowError,
  jobsForDay,
  localToIso,
  technicianInitials,
  unscheduledJobs,
} from "./job-derivations";

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
});
