import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { NextRequest } from "next/server";

import {
  CONSOLE_AUTH_COOKIE,
  getConfiguredConsoleToken,
  isAllowedFrontendHost,
} from "../src/lib/server/consoleAuth";
import { middleware } from "../src/middleware";

const ROOT = process.cwd();

test("server token accepts only a sufficiently long URL-safe value", () => {
  const previous = process.env["CONSOLE_AUTH_TOKEN"];
  try {
    process.env["CONSOLE_AUTH_TOKEN"] = "short";
    assert.equal(getConfiguredConsoleToken(), null);

    process.env["CONSOLE_AUTH_TOKEN"] = "not-safe+token/not-safe+token/not-safe";
    assert.equal(getConfiguredConsoleToken(), null);

    const valid = "local-console-token_00000000000000000000";
    process.env["CONSOLE_AUTH_TOKEN"] = valid;
    assert.equal(getConfiguredConsoleToken(), valid);
  } finally {
    if (previous === undefined) delete process.env["CONSOLE_AUTH_TOKEN"];
    else process.env["CONSOLE_AUTH_TOKEN"] = previous;
  }
});

test("frontend Host parser accepts only canonical loopback authorities", () => {
  for (const host of [
    "localhost",
    "LOCALHOST:4000",
    "127.0.0.1",
    "127.0.0.1:65535",
    "[::1]",
    "[::1]:4000",
  ]) {
    assert.equal(isAllowedFrontendHost(host), true, host);
  }

  for (const host of [
    null,
    "",
    " localhost",
    "localhost.",
    "localhost:0",
    "localhost:65536",
    "localhost:4000,attacker.test",
    "127.0.0.1.attacker.test",
    "127.1",
    "::1",
    "[::1",
    "attacker.test",
  ]) {
    assert.equal(isAllowedFrontendHost(host), false, String(host));
  }
});

test("middleware rejects a bad raw Host before token lookup or injection", async () => {
  const previous = process.env["CONSOLE_AUTH_TOKEN"];
  try {
    delete process.env["CONSOLE_AUTH_TOKEN"];
    const request = new NextRequest("http://127.0.0.1:4000/api/browser-smoke", {
      headers: {
        host: "console.attacker.test",
        origin: "https://console.attacker.test",
      },
    });

    const response = middleware(request);

    assert.equal(response.status, 403);
    assert.deepEqual(await response.json(), { detail: "host_not_allowed" });
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(response.headers.get("set-cookie"), null);
    assert.equal(response.headers.get("x-middleware-request-cookie"), null);
    assert.equal(response.cookies.get(CONSOLE_AUTH_COOKIE), undefined);
  } finally {
    if (previous === undefined) delete process.env["CONSOLE_AUTH_TOKEN"];
    else process.env["CONSOLE_AUTH_TOKEN"] = previous;
  }
});

test("loopback middleware request gets a strict HttpOnly cookie and preserves Origin", () => {
  const previous = process.env["CONSOLE_AUTH_TOKEN"];
  const token = "local-console-token_00000000000000000000";
  try {
    process.env["CONSOLE_AUTH_TOKEN"] = token;
    const request = new NextRequest("http://127.0.0.1:4000/api/browser-smoke", {
      headers: {
        host: "127.0.0.1:4000",
        origin: "http://127.0.0.1:4000",
        cookie: `${CONSOLE_AUTH_COOKIE}=stale; preference=compact`,
      },
    });

    const response = middleware(request);
    const cookie = response.cookies.get(CONSOLE_AUTH_COOKIE);

    assert.equal(response.status, 200);
    assert.equal(response.headers.get("x-middleware-next"), "1");
    assert.equal(response.headers.get("x-middleware-request-origin"), "http://127.0.0.1:4000");
    assert.equal(
      response.headers.get("x-middleware-request-cookie"),
      `preference=compact; ${CONSOLE_AUTH_COOKIE}=${token}`,
    );
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.ok(cookie);
    assert.equal(cookie.value, token);
    assert.equal(cookie.httpOnly, true);
    assert.equal(cookie.sameSite, "strict");
    assert.equal(cookie.secure, false);
    assert.equal(cookie.path, "/");
  } finally {
    if (previous === undefined) delete process.env["CONSOLE_AUTH_TOKEN"];
    else process.env["CONSOLE_AUTH_TOKEN"] = previous;
  }
});

test("browser auth uses an HttpOnly strict cookie without returning the token", () => {
  const helper = readFileSync(join(ROOT, "src/lib/server/consoleAuth.ts"), "utf-8");
  const route = readFileSync(join(ROOT, "src/app/console-auth/route.ts"), "utf-8");
  const middleware = readFileSync(join(ROOT, "src/middleware.ts"), "utf-8");

  assert.match(helper, /httpOnly: true/);
  assert.match(helper, /sameSite: "strict"/);
  assert.match(route, /\{ ready: true \}/);
  assert.doesNotMatch(route, /\{\s*token\s*:/);
  assert.match(middleware, /requestHeadersWithConsoleCookie/);
});

test("default WebSocket transport follows the current browser hostname", () => {
  const source = readFileSync(join(ROOT, "src/lib/api/fetch.ts"), "utf-8");

  assert.match(source, /window\.location\.hostname/);
  assert.match(source, /window\.location\.protocol === "https:" \? "wss:" : "ws:"/);
  assert.doesNotMatch(source, /\?\? "ws:\/\/localhost:9000"/);
});

test("default API rewrite targets the explicit IPv4 loopback backend", () => {
  const source = readFileSync(join(ROOT, "next.config.ts"), "utf-8");

  assert.match(source, /\?\? "http:\/\/127\.0\.0\.1:9000"/);
  assert.doesNotMatch(source, /\?\? "http:\/\/localhost:9000"/);
});
