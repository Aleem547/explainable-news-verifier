/* eslint-disable @typescript-eslint/no-require-imports -- Node test harness. */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function load(file, mocks) {
  const filename = path.resolve(__dirname, "../src", file);
  const result = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    fileName: filename, reportDiagnostics: true,
  });
  assert.equal((result.diagnostics || []).filter(d => d.category === ts.DiagnosticCategory.Error).length, 0);
  const mod = new Module(filename);
  mod.filename = filename; mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const normal = mod.require.bind(mod);
  mod.require = name => Object.hasOwn(mocks, name) ? mocks[name] : normal(name);
  mod._compile(result.outputText, filename);
  return mod.exports;
}

function navigation(session, order = []) {
  return load("components/auth/auth-navigation.tsx", {
    "next/link": { __esModule: true, default: props => React.createElement("a", props, props.children) },
    "next/server": { connection: async () => { order.push("request"); } },
    "@/auth": { auth: async () => { order.push("session"); return session; } },
    "@/app/auth-actions": { logOut: async () => {} },
  });
}

test("signed-out visitors get usable login and signup links", async () => {
  const order = [];
  const loaded = navigation(null, order);
  const html = renderToStaticMarkup(await loaded.AuthNavigation());
  assert.deepEqual(order, ["request", "session"]);
  assert.match(html, /href="\/login"[^>]*>Log in</);
  assert.match(html, /href="\/signup"[^>]*>Sign up</);
  assert.doesNotMatch(html, /My account|Log out/);
});

test("sessions without the verified identity do not show authenticated controls", async () => {
  const html = renderToStaticMarkup(await navigation({ user: { name: "Incomplete" } }).AuthNavigation());
  assert.match(html, /href="\/login"/);
  assert.doesNotMatch(html, /Incomplete/);
});

test("signed-in controls show account and logout without exposing identity data", async () => {
  const html = renderToStaticMarkup(await navigation({ user: { id: "google:synthetic", name: "Synthetic User", email: "synthetic@example.invalid" } }).AuthNavigation());
  assert.match(html, /href="\/account"[^>]*>My account</);
  assert.match(html, />Log out</);
  assert.doesNotMatch(html, /google:synthetic|Synthetic User|synthetic@example.invalid|href="\/signup"|href="\/login"/);
});

test("Google entry and logout use fixed internal destinations", async () => {
  const calls = [];
  const actions = load("app/auth-actions.ts", { "@/auth": {
    signIn: async (...args) => calls.push(["login", ...args]),
    signOut: async (...args) => calls.push(["logout", ...args]),
  } });
  const injected = new FormData(); injected.set("redirectTo", "https://example.invalid/");
  await actions.logInWithGoogle(injected);
  await actions.logOut(injected);
  assert.deepEqual(calls, [["login", "google", { redirectTo: "/verify" }], ["logout", { redirectTo: "/" }]]);
});
