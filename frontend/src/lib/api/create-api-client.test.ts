import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/msw/server";
import type { PaginatedResponse } from "@/types/api";

import {
  createApiClient,
  createNonWorkspaceApiClient,
  type FullApiClient,
} from "./create-api-client";

/**
 * The axios client resolves relative URLs against the jsdom origin
 * (`http://localhost:3000`). Register handlers there so requests are matched.
 */
const ORIGIN = "http://localhost:3000";

interface Widget {
  id: number;
  name: string;
}

interface CreateWidget {
  name: string;
}

interface UpdateWidget {
  name?: string;
}

function makeList(items: Widget[]): PaginatedResponse<Widget> {
  return { items, total: items.length, page: 1, page_size: 50, pages: 1 };
}

describe("createApiClient — workspace-scoped CRUD", () => {
  const client = createApiClient<Widget, CreateWidget, UpdateWidget>({
    resourcePath: "widgets",
  }) as FullApiClient<Widget, CreateWidget, UpdateWidget>;

  it("lists resources and forwards query params", async () => {
    let capturedParams: URLSearchParams | null = null;
    server.use(
      http.get(`${ORIGIN}/api/v1/workspaces/:workspaceId/widgets`, ({ request, params }) => {
        capturedParams = new URL(request.url).searchParams;
        expect(params.workspaceId).toBe("ws_1");
        return HttpResponse.json(makeList([{ id: 1, name: "Alpha" }]));
      }),
    );

    const result = await client.list("ws_1", { search: "alp", page: 2 });

    expect(result.items).toEqual([{ id: 1, name: "Alpha" }]);
    expect(capturedParams!.get("search")).toBe("alp");
    expect(capturedParams!.get("page")).toBe("2");
  });

  it("defaults to an empty params object when none are provided", async () => {
    let searchString = "unset";
    server.use(
      http.get(`${ORIGIN}/api/v1/workspaces/:workspaceId/widgets`, ({ request }) => {
        searchString = new URL(request.url).search;
        return HttpResponse.json(makeList([]));
      }),
    );

    await client.list("ws_1");

    expect(searchString).toBe("");
  });

  it("gets a single resource by id, interpolating the path", async () => {
    server.use(
      http.get(`${ORIGIN}/api/v1/workspaces/:workspaceId/widgets/:id`, ({ params }) => {
        expect(params.workspaceId).toBe("ws_1");
        expect(params.id).toBe("7");
        return HttpResponse.json({ id: 7, name: "Lucky" });
      }),
    );

    const widget = await client.get("ws_1", 7);

    expect(widget).toEqual({ id: 7, name: "Lucky" });
  });

  it("creates a resource via POST and returns the created body", async () => {
    let received: unknown = null;
    server.use(
      http.post(`${ORIGIN}/api/v1/workspaces/:workspaceId/widgets`, async ({ request }) => {
        received = await request.json();
        return HttpResponse.json({ id: 99, name: "Created" });
      }),
    );

    const created = await client.create("ws_1", { name: "Created" });

    expect(received).toEqual({ name: "Created" });
    expect(created).toEqual({ id: 99, name: "Created" });
  });

  it("updates a resource via PUT at the id path", async () => {
    let received: unknown = null;
    server.use(
      http.put(`${ORIGIN}/api/v1/workspaces/:workspaceId/widgets/:id`, async ({ request, params }) => {
        received = await request.json();
        expect(params.id).toBe("7");
        return HttpResponse.json({ id: 7, name: "Renamed" });
      }),
    );

    const updated = await client.update("ws_1", 7, { name: "Renamed" });

    expect(received).toEqual({ name: "Renamed" });
    expect(updated).toEqual({ id: 7, name: "Renamed" });
  });

  it("deletes a resource via DELETE at the id path", async () => {
    let hit = false;
    server.use(
      http.delete(`${ORIGIN}/api/v1/workspaces/:workspaceId/widgets/:id`, ({ params }) => {
        hit = true;
        expect(params.id).toBe("7");
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await expect(client.delete("ws_1", 7)).resolves.toBeUndefined();
    expect(hit).toBe(true);
  });

  it("rejects when the backend returns an error status", async () => {
    server.use(
      http.get(`${ORIGIN}/api/v1/workspaces/:workspaceId/widgets/:id`, () =>
        HttpResponse.json({ message: "not found" }, { status: 404 }),
      ),
    );

    await expect(client.get("ws_1", 404)).rejects.toThrow();
  });
});

describe("createApiClient — transforms", () => {
  it("applies the item transform to single-resource responses", async () => {
    const client = createApiClient<Widget, CreateWidget, UpdateWidget>({
      resourcePath: "widgets",
      transform: (raw) => {
        const r = raw as { id: number; name: string };
        return { id: r.id, name: r.name.toUpperCase() };
      },
    }) as FullApiClient<Widget, CreateWidget, UpdateWidget>;

    server.use(
      http.get(`${ORIGIN}/api/v1/workspaces/:workspaceId/widgets/:id`, () =>
        HttpResponse.json({ id: 1, name: "alpha" }),
      ),
    );

    const widget = await client.get("ws_1", 1);
    expect(widget.name).toBe("ALPHA");
  });

  it("maps the item transform over list items when no list transform is given", async () => {
    const client = createApiClient<Widget, CreateWidget, UpdateWidget>({
      resourcePath: "widgets",
      transform: (raw) => {
        const r = raw as { id: number; name: string };
        return { id: r.id, name: r.name.toUpperCase() };
      },
    });

    server.use(
      http.get(`${ORIGIN}/api/v1/workspaces/:workspaceId/widgets`, () =>
        HttpResponse.json(makeList([{ id: 1, name: "a" }, { id: 2, name: "b" }])),
      ),
    );

    const result = await client.list("ws_1");
    expect(result.items.map((w) => w.name)).toEqual(["A", "B"]);
    expect(result.total).toBe(2);
  });

  it("uses a dedicated list transform when provided", async () => {
    const client = createApiClient<Widget, CreateWidget, UpdateWidget>({
      resourcePath: "widgets",
      transformList: (raw) => {
        const r = raw as { results: Widget[] };
        return { items: r.results, total: r.results.length, page: 1, page_size: 50, pages: 1 };
      },
    });

    server.use(
      http.get(`${ORIGIN}/api/v1/workspaces/:workspaceId/widgets`, () =>
        HttpResponse.json({ results: [{ id: 5, name: "five" }] }),
      ),
    );

    const result = await client.list("ws_1");
    expect(result.items).toEqual([{ id: 5, name: "five" }]);
  });
});

describe("createApiClient — method inclusion flags", () => {
  it("omits the methods that are disabled", () => {
    const client = createApiClient<Widget, CreateWidget, UpdateWidget>({
      resourcePath: "widgets",
      includeGet: false,
      includeCreate: false,
      includeUpdate: false,
      includeDelete: false,
    });

    expect(typeof client.list).toBe("function");
    expect(client.get).toBeUndefined();
    expect(client.create).toBeUndefined();
    expect(client.update).toBeUndefined();
    expect(client.delete).toBeUndefined();
  });
});

describe("createNonWorkspaceApiClient", () => {
  it("targets the unscoped `/api/v1/<resource>` path", async () => {
    const client = createNonWorkspaceApiClient<Widget, CreateWidget, UpdateWidget>({
      resourcePath: "globals",
    });

    let hit = false;
    server.use(
      http.get(`${ORIGIN}/api/v1/globals`, () => {
        hit = true;
        return HttpResponse.json(makeList([{ id: 1, name: "g" }]));
      }),
    );

    // First arg is unused for the path but kept for signature compatibility.
    const result = await client.list("ignored");
    expect(hit).toBe(true);
    expect(result.items).toHaveLength(1);
  });
});
