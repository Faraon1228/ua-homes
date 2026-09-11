const { test, expect } = require("@playwright/test");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const vm = require("node:vm");

const web = resolve(__dirname, "../../web");
const read = (name) => readFileSync(resolve(web, name), "utf8");

test.use({ serviceWorkers: "block" });

test("the approved artwork is versioned consistently with the shell and precache", () => {
  const manifest = { self: {} };
  vm.runInNewContext(read("precache-manifest.js"), manifest);
  const html = read("real-estate-demo.html");
  const cssVersion = html.match(/ua-homes\.css\?v=(perf-[a-f0-9]{12})/)[1];
  const asset = `/images/silver-silhouette.svg?v=${cssVersion}`;
  expect(html.split(`src="${asset}"`)).toHaveLength(3);
  expect(manifest.self.__UA_PRECACHE_ASSETS).toContain(asset);
  expect(manifest.self.__UA_BUILD_ID).toMatch(/^[a-f0-9]{12}$/);
  const svg = read("images/silver-silhouette.svg");
  expect(svg).toContain('viewBox="0 0 1600 900"');
  for (const detail of ["windows", "balconies", "side-windows", "details"]) {
    expect(svg).toContain(`id="${detail}"`);
  }
  const build = readFileSync(resolve(web, "../scripts/rebuild-frontend.sh"), "utf8");
  for (const block of ["ASSET_VERSION", "BUILD_ID"]) {
    expect(build.split(`${block}=$(`)[1].split("| shasum")[0])
      .toContain('"$WEB_DIR/images/silver-silhouette.svg"');
  }
  const netlify = readFileSync(resolve(web, "../netlify.toml"), "utf8");
  for (const path of ["/", "/app", "/seller"]) {
    expect(netlify).toContain(`from = "${path}"\n  to = "/real-estate-demo.html"\n  status = 200`);
  }
});

test("the worker serves fresh artwork online and the shell copy offline, never stale listing photos", async () => {
  const handlers = {};
  const openedCaches = [];
  const matches = [];
  const updates = [];
  const networkResponse = { status: 200, clone: () => networkResponse };
  const offlineResponse = { status: 200, source: "precache" };
  const staleImageResponse = { status: 200, source: "old image cache" };
  const currentUrl = "https://ua-dim.com/images/silver-silhouette.svg?v=perf-current";
  let online = true;
  const scope = {
    URL, Response,
    importScripts() {},
    self: {
      __UA_BUILD_ID: "test-release",
      location: { origin: "https://ua-dim.com" },
      addEventListener: (name, handler) => { handlers[name] = handler; },
    },
    fetch: async () => {
      if (!online) throw new Error("offline");
      return networkResponse;
    },
    caches: {
      open: async (name) => {
        openedCaches.push(name);
        return {
          put: async (request) => { updates.push(request.url); },
          match: async (request, options) => {
            matches.push({ cache: name, url: request.url, options });
            return request.url === currentUrl ? offlineResponse : undefined;
          },
        };
      },
      match: async () => staleImageResponse,
    },
  };
  vm.runInNewContext(read("sw.js"), scope);
  const request = {
    method: "GET", destination: "image",
    url: currentUrl,
  };
  let response;
  const event = { request, respondWith: (promise) => { response = promise; } };
  handlers.fetch(event);
  expect(await response).toBe(networkResponse);
  expect(openedCaches).toEqual(["ua-dim-v6-test-release"]);
  expect(updates).toEqual([request.url]);
  expect(matches).toHaveLength(0);
  online = false;
  handlers.fetch(event);
  expect(await response).toBe(offlineResponse);
  expect(matches).toEqual([{ cache: "ua-dim-v6-test-release", url: currentUrl, options: undefined }]);
  request.url = currentUrl.replace("current", "different");
  handlers.fetch(event);
  expect((await response).type).toBe("error");
  expect(openedCaches).not.toContain("ua-dim-images-v1");
});

test("worker upgrade cannot serve an old photo-cache SVG over the current offline shell", async ({ page }) => {
  await page.goto("/privacy.html");
  const result = await page.evaluate(async (source) => {
    const oldUrl = new URL("/images/silver-silhouette.svg?v=perf-old", location.origin).href;
    const newUrl = new URL("/images/silver-silhouette.svg?v=perf-new", location.origin).href;
    const imageCache = await caches.open("ua-dim-images-v1");
    await imageCache.put(oldUrl, new Response("OLD artwork"));
    const shellCache = await caches.open("ua-dim-v6-test-release");
    await shellCache.put(newUrl, new Response("NEW artwork"));
    const handlers = {};
    const worker = {
      __UA_BUILD_ID: "test-release",
      location: { origin: location.origin },
      clients: { claim: async () => {} },
      addEventListener: (type, handler) => { handlers[type] = handler; },
    };
    const offlineFetch = async () => { throw new Error("offline"); };
    new Function("self", "importScripts", "fetch", source)(worker, () => {}, offlineFetch);
    let activation;
    handlers.activate({ waitUntil: (promise) => { activation = promise; } });
    await activation;
    let response;
    handlers.fetch({
      request: new Request(newUrl),
      respondWith: (promise) => { response = promise; },
    });
    return {
      artwork: await (await response).text(),
      oldArtwork: await (await imageCache.match(oldUrl)).text(),
    };
  }, read("sw.js"));
  expect(result).toEqual({ artwork: "NEW artwork", oldArtwork: "OLD artwork" });
});
