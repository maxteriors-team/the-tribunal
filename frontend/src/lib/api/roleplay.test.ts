import type { AxiosAdapter } from "axios";
import { afterEach, describe, expect, it } from "vitest";

import { api } from "@/lib/api";
import { roleplayApi } from "@/lib/api/roleplay";

const originalAdapter = api.defaults.adapter;
afterEach(() => {
  api.defaults.adapter = originalAdapter;
  sessionStorage.clear();
});

function capture(respond: (body: Record<string, unknown>) => unknown): void {
  const adapter: AxiosAdapter = async (config) => {
    if (typeof config.data !== "string") throw new Error("Expected JSON request");
    const body: Record<string, unknown> = JSON.parse(config.data);
    return { data: respond(body), status: 202, statusText: "Accepted", headers: {}, config };
  };
  api.defaults.adapter = adapter;
}

const request = { agent_id: "agent", persona_id: "persona", max_turns: 6 };

describe("durable rehearsal requests", () => {
  it("reuses the creation identity after a lost response, then rotates after acceptance", async () => {
    const keys: unknown[] = [];
    capture((body) => {
      keys.push(body.idempotency_key);
      throw new Error("lost response");
    });
    await expect(roleplayApi.createRun("lost-response-test", request)).rejects.toThrow(
      "lost response",
    );
    expect(sessionStorage.getItem("roleplay:pending-create:lost-response-test")).toContain(
      String(keys[0]),
    );
    capture((body) => {
      keys.push(body.idempotency_key);
      return { id: "saved-run", status: "pending" };
    });
    expect((await roleplayApi.createRun("lost-response-test", request)).id).toBe("saved-run");
    await roleplayApi.createRun("lost-response-test", request);
    expect(keys[0]).toBe(keys[1]);
    expect(keys[2]).not.toBe(keys[1]);
    expect(sessionStorage.getItem("roleplay:pending-create:lost-response-test")).toBeNull();
  });

  it("recovers an unresolved identity from browser storage after remount/reload", async () => {
    const key = crypto.randomUUID();
    sessionStorage.setItem(
      "roleplay:pending-create:reload-test",
      JSON.stringify({
        key,
        fingerprint: JSON.stringify(["agent", "persona", "ai", null, 6]),
      }),
    );
    capture((body) => {
      expect(body.idempotency_key).toBe(key);
      return { id: "recovered" };
    });
    await roleplayApi.createRun("reload-test", request);
  });

  it("sends observed step versions for retry and manual-turn deduplication", async () => {
    const bodies: Record<string, unknown>[] = [];
    capture((body) => {
      bodies.push(body);
      return { id: "run", status: "pending" };
    });
    await roleplayApi.advanceTurn("workspace", "run", "Hello", 3);
    await roleplayApi.retryRun("workspace", "run", 4);
    expect(bodies).toEqual([
      { message: "Hello", expected_turn_count: 3 },
      { expected_attempt_count: 4 },
    ]);
  });
});
