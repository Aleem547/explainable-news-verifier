import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import os from "node:os";
import { chromium } from "playwright";
import { encode } from "next-auth/jwt";

const root = fileURLToPath(new URL("../", import.meta.url));
const port = 4317;
const base = `http://127.0.0.1:${port}`;
const secret = "synthetic-local-auth-navigation-secret-for-tests-only";
const output = process.env.AUTH_TEST_OUTPUT || path.join(os.tmpdir(), `verifier-auth-ui-${Date.now()}`);
await mkdir(output, { recursive: true });
const server = spawn(process.execPath, ["--import", fileURLToPath(new URL("./auth_oidc_fixture.mjs", import.meta.url)),
  path.join(root, "node_modules/next/dist/bin/next"), "start", "--hostname", "127.0.0.1", "--port", String(port)], {
  cwd: root,
  env: { ...process.env, NODE_ENV: "production", AUTH_SECRET: secret, AUTH_TRUST_HOST: "true", AUTH_URL: base,
    AUTH_GOOGLE_ID: "synthetic-local-google-client", AUTH_GOOGLE_SECRET: "synthetic-local-google-secret",
    ARTICLE_VERIFICATION_ENABLED: "true", VERIFY_REQUIRE_LOGIN: "true",
    API_BASE_URL: "https://backend.example.invalid", INTERNAL_API_TOKEN: "synthetic-local-service-token-for-tests-only",
    NEXT_TELEMETRY_DISABLED: "1" },
  stdio: ["ignore", "pipe", "pipe"],
});
let logs = "";
server.stdout.on("data", chunk => { logs = (logs + chunk).slice(-12000); });
server.stderr.on("data", chunk => { logs = (logs + chunk).slice(-12000); });
const checks = [];
let browser;
try {
  for (let count = 0; ; count++) {
    try { const response = await fetch(base); if (response.ok) break; } catch {}
    if (count > 100 || server.exitCode !== null) throw new Error("Local production server did not start");
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  browser = await chromium.launch({ headless: true,
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}) });
  const guest = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await guest.newPage();
  const nav = target => target.getByRole("navigation", { name: "Account navigation" });
  for (const route of ["/", "/verify", "/article", "/account", "/login", "/signup"]) {
    await page.goto(base + route);
    await nav(page).getByRole("link", { name: "Log in", exact: true }).waitFor();
    await nav(page).getByRole("link", { name: "Sign up", exact: true }).waitFor();
    checks.push(`signed_out_navigation:${route}`);
  }
  await page.getByRole("button", { name: "Continue with Google", exact: true }).waitFor();
  await page.screenshot({ path: path.join(output, "signup-desktop.png"), fullPage: true });
  for (const [route, heading] of [["/login", "Welcome back"], ["/signup", "Create your account"]]) {
    let oauthUrl;
    await page.route("https://accounts.google.com/**", async route => {
      oauthUrl = new URL(route.request().url());
      await route.fulfill({ status: 200, contentType: "text/html", body: "<h1>Local OAuth redirect checked</h1>" });
    });
    await page.goto(base + route);
    await page.getByRole("heading", { name: heading }).waitFor();
    await page.getByRole("button", { name: "Continue with Google", exact: true }).click();
    await page.getByRole("heading", { name: "Local OAuth redirect checked" }).waitFor();
    assert.equal(oauthUrl.hostname, "accounts.google.com");
    assert.equal(oauthUrl.searchParams.get("client_id"), "synthetic-local-google-client");
    assert.equal(oauthUrl.searchParams.get("redirect_uri"), base + "/api/auth/callback/google");
    assert.equal(oauthUrl.searchParams.get("code_challenge_method"), "S256");
    await page.unroute("https://accounts.google.com/**");
    checks.push(`real_authjs_oauth_start:${route}`);
  }
  const token = await encode({ secret, salt: "authjs.session-token", maxAge: 3600,
    token: { sub: "synthetic-ui-test", verifiedSubject: "google:synthetic-ui-test", name: "Local UI Tester", email: "ui-test@example.invalid" } });
  const member = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await member.addCookies([{ name: "authjs.session-token", value: token, url: base, httpOnly: true, sameSite: "Lax" }]);
  const signedIn = await member.newPage();
  await signedIn.goto(base + "/verify");
  await nav(signedIn).getByRole("link", { name: "My account", exact: true }).waitFor();
  await nav(signedIn).getByRole("button", { name: "Log out", exact: true }).waitFor();
  assert.equal(await nav(signedIn).getByRole("link", { name: "Sign up", exact: true }).count(), 0);
  checks.push("signed_in_account_and_logout");
  await page.goto(base + "/");
  await nav(page).getByRole("link", { name: "Sign up", exact: true }).waitFor();
  assert.equal(await nav(page).getByRole("link", { name: "My account", exact: true }).count(), 0);
  checks.push("separate_visitor_session_isolation");
  await signedIn.goto(base + "/account");
  await signedIn.getByText("ui-test@example.invalid", { exact: true }).waitFor();
  await nav(signedIn).getByRole("button", { name: "Log out", exact: true }).click();
  await signedIn.waitForURL(base + "/");
  await nav(signedIn).getByRole("link", { name: "Log in", exact: true }).waitFor();
  const cookies = await member.cookies();
  assert.equal(cookies.filter(c => c.name === "authjs.session-token").length, 0);
  checks.push("real_server_action_logout_clears_session");
  for (const [route, body] of [["/api/verification", { claim: "The Eiffel Tower is in Paris.", top_k: 5 }],
    ["/api/article-verification", { kind: "pasted", text: "Chandrayaan-3 landed on the Moon.\nThis background paragraph explains the scope of this local check without adding independent evidence." }]]) {
    const response = await guest.request.post(base + route, { data: body });
    assert.equal(response.status(), 401);
    checks.push(`unauthenticated_verification_rejected:${route}`);
  }
  const mobile = await browser.newContext({ viewport: { width: 320, height: 740 }, isMobile: true, hasTouch: true });
  const phone = await mobile.newPage();
  for (const route of ["/", "/signup"]) {
    await phone.goto(base + route);
    await nav(phone).getByRole("link", { name: "Sign up", exact: true }).waitFor();
    assert.equal(await phone.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await phone.evaluate(() => scrollTo(0, 1200));
    const box = await nav(phone).getByRole("link", { name: "Log in", exact: true }).boundingBox();
    const header = await phone.locator("body > header").boundingBox();
    assert.ok(header && header.y < 1 && header.y + header.height > 0 && header.height < 370,
      JSON.stringify({ header, box }));
    assert.ok(box && box.y >= 0 && box.y >= header.y && box.y + box.height <= Math.min(740, header.y + header.height) &&
      box.x >= 0 && box.x + box.width <= 320);
    checks.push(`mobile_visible_auth_controls:${route}`);
  }
  await phone.getByRole("button", { name: "Continue with Google", exact: true }).waitFor();
  await phone.screenshot({ path: path.join(output, "signup-mobile.png"), fullPage: true });
  const result = { status: "LOCAL_AUTH_UI_BROWSER_CHECKS_PASSED", checks: checks.length, names: checks,
    next_production_build: true, authjs_redirect_and_logout_exercised: true,
    google_discovery_metadata: "local fixture", signed_in_identity: "synthetic local JWT only",
    live_google_account_login_completed: false, production_deployment_performed: false, output };
  await writeFile(path.join(output, "RESULT.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} catch (error) {
  await writeFile(path.join(output, "server.log"), logs);
  console.error(error.stack); console.error("Local test logs: " + path.join(output, "server.log"));
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
  server.kill("SIGTERM");
  await new Promise(resolve => { if (server.exitCode !== null) resolve(); else server.once("exit", resolve); });
}
