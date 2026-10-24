import assert from "node:assert/strict";
import test from "node:test";

import type { V1ModelEntry, V1ModelsResponse } from "./api.ts";
import {
  beginModelsCatalogRefresh,
  buildCatalogFromV1Response,
  createInitialCatalogLoadState,
  emptyModelsCatalog,
  invalidateModelsCatalogState,
  settleModelsCatalogRequest,
  type ModelsCatalogData,
  type ModelsCatalogLoadState,
} from "./modelsCatalog.ts";

function entry(id: string, extras: Record<string, unknown> = {}): V1ModelEntry {
  return {
    id,
    object: "model",
    created: 0,
    owned_by: "lmpanel",
    description: `${id} description`,
    context_length: 8192,
    ...extras,
  } as V1ModelEntry;
}

function response(data: unknown): V1ModelsResponse {
  return { object: "list", data } as V1ModelsResponse;
}

function catalogWith(ids: string[]): ModelsCatalogData {
  return buildCatalogFromV1Response(response(ids.map((id) => entry(id))));
}

function loaded(ids: string[]): ModelsCatalogLoadState {
  return {
    catalog: ids.length > 0 ? catalogWith(ids) : emptyModelsCatalog,
    isLoadingModels: false,
    isRefreshingModels: false,
  };
}

test("catalog keeps models that are still starting, recovering, or in error", () => {
  const catalog = buildCatalogFromV1Response(response([
    entry("loaded", { status: "running" }),
    entry("starting", { status: "starting", runtime_state: "starting" }),
    entry("recovering", { status: "recovering" }),
    entry("failed", { status: "error", runtime_state: "degraded" }),
    entry("unavailable", { status: "unavailable" }),
    entry("backoff", { status: "backoff_limited" }),
    { status: "stopped" },
    null,
    entry("loaded"),
  ]));

  assert.deepEqual(catalog.models, ["loaded", "starting", "recovering", "failed", "unavailable", "backoff"]);
  assert.equal(catalog.modelCardDetails.starting.description, "starting description");
});

test("malformed catalog payloads fail instead of being treated as an empty list", () => {
  assert.throws(() => buildCatalogFromV1Response(response(null)), /Failed to load models/);
  assert.throws(() => buildCatalogFromV1Response({ object: "list" } as V1ModelsResponse), /Failed to load models/);
  assert.throws(() => buildCatalogFromV1Response({ status: "starting" } as V1ModelsResponse), /Failed to load models/);
});

test("enabling or disabling a model reloads the list and clears the skeleton", () => {
  const previous = loaded(["alpha"]);
  let requestId = 1;
  let state = invalidateModelsCatalogState();
  requestId += 1;

  assert.equal(state.isLoadingModels, true);
  assert.deepEqual(state.catalog.models, []);

  state = beginModelsCatalogRefresh(state);
  assert.equal(state.isLoadingModels, true);

  state = settleModelsCatalogRequest(state, 1, requestId, { ok: true, catalog: previous.catalog });
  assert.equal(state.isLoadingModels, true);
  assert.deepEqual(state.catalog.models, []);

  state = settleModelsCatalogRequest(state, requestId, requestId, { ok: true, catalog: catalogWith(["beta"]) });
  assert.equal(state.isLoadingModels, false);
  assert.equal(state.isRefreshingModels, false);
  assert.deepEqual(state.catalog.models, ["beta"]);
});

test("a failed reload after a status change clears the skeleton", () => {
  let state = invalidateModelsCatalogState();
  state = beginModelsCatalogRefresh(state);
  state = settleModelsCatalogRequest(state, 2, 2, { ok: false });

  assert.equal(state.isLoadingModels, false);
  assert.equal(state.isRefreshingModels, false);
  assert.deepEqual(state.catalog.models, []);
});

test("an in-place refresh keeps the current list until the new one arrives", () => {
  const current = loaded(["alpha"]);
  const refreshing = beginModelsCatalogRefresh(current);
  assert.equal(refreshing.isLoadingModels, false);
  assert.equal(refreshing.isRefreshingModels, true);
  assert.deepEqual(refreshing.catalog.models, ["alpha"]);

  const settled = settleModelsCatalogRequest(refreshing, 4, 4, { ok: true, catalog: catalogWith(["alpha", "beta"]) });
  assert.equal(settled.isLoadingModels, false);
  assert.equal(settled.isRefreshingModels, false);
  assert.deepEqual(settled.catalog.models, ["alpha", "beta"]);
});

test("a stale refresh cannot finish a newer status-change reload", () => {
  const started = beginModelsCatalogRefresh(invalidateModelsCatalogState());
  const staleFailure = settleModelsCatalogRequest(started, 1, 3, { ok: false });
  const staleSuccess = settleModelsCatalogRequest(started, 2, 3, {
    ok: true,
    catalog: catalogWith(["stale"]),
  });

  assert.equal(staleFailure, started);
  assert.equal(staleSuccess, started);
  assert.equal(started.isLoadingModels, true);
  assert.deepEqual(started.catalog.models, []);
});

test("initial load shows the skeleton only when nothing is cached", () => {
  const cold = createInitialCatalogLoadState(null);
  assert.equal(cold.isLoadingModels, true);
  assert.deepEqual(cold.catalog.models, []);

  const warm = createInitialCatalogLoadState(catalogWith(["alpha"]));
  assert.equal(warm.isLoadingModels, false);
  assert.deepEqual(warm.catalog.models, ["alpha"]);

  const failedColdLoad = settleModelsCatalogRequest(beginModelsCatalogRefresh(cold), 1, 1, { ok: false });
  assert.equal(failedColdLoad.isLoadingModels, false);
});
