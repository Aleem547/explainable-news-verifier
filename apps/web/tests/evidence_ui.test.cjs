/* eslint-disable @typescript-eslint/no-require-imports -- Node test harness. */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const { makeReport, oldCodes } = require("./evidence_ui_fixture.cjs");

function load(file, mocks = {}) {
  const filename = path.resolve(__dirname, "../src", file);
  const output = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true }, fileName: filename,
  });
  const mod = new Module(filename);
  mod.filename = filename; mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const normal = mod.require.bind(mod);
  mod.require = name => Object.hasOwn(mocks, name) ? mocks[name] : normal(name);
  mod._compile(output.outputText, filename);
  return mod.exports;
}

const contract = load("lib/api/article-contracts.ts");
const { ArticleEvidenceNotices } = load("components/verification/article-evidence-notices.tsx");
const { ArticleEvidenceDetails } = load("components/verification/article-evidence-details.tsx", {
  "@/lib/api/article-contracts": contract,
});
const render = claim => renderToStaticMarkup(React.createElement(ArticleEvidenceNotices, { claim }));

test("presentation fixtures pass the unchanged public response guard", () => {
  for (const state of ["support", "refute", "conflicting", "pending", "unavailable", "insufficient", "legacy"]) {
    assert.equal(contract.isArticleVerificationReport(makeReport(state)), true, state);
  }
});

test("reviewed support and refutation retain their claim and evidence limits", () => {
  for (const state of ["support", "refute"]) {
    const html = render(makeReport(state).claims[0]);
    assert.match(html, state === "support" ? /Reviewed cross-source support applies only/ : /Reviewed cross-source refutation applies only/);
    assert.match(html, /not factual truth probabilities/);
    assert.match(html, /No article-wide truth rating/);
    assert.doesNotMatch(html, /corroboration is not established/);
  }
});

test("pending and unavailable reviews never turn high NLI scores into corroboration", () => {
  for (const state of ["pending", "unavailable", "legacy"]) {
    const html = render(makeReport(state).claims[0]);
    assert.match(html, /corroboration is not established for this claim/);
    assert.doesNotMatch(html, /Reviewed cross-source support applies/);
  }
  const report = makeReport("support");
  report.claims[0].external_reviewed_corroboration.corroboration_established = false;
  assert.equal(contract.isArticleVerificationReport(report), false);
  assert.doesNotMatch(render(report.claims[0]), /Reviewed cross-source support applies/);
});

test("conflicts and insufficient evidence remain visible in plain language", () => {
  assert.match(render(makeReport("conflicting").claims[0]), /both support and refutation/);
  const html = render(makeReport("insufficient").claims[0]);
  assert.match(html, /stored external evidence is insufficient/);
  assert.match(html, /does not establish that the claim is false/);
});

test("all raw codes including unknown codes are preserved in collapsed diagnostics", () => {
  const claim = makeReport("support").claims[0];
  const before = JSON.stringify(claim);
  const html = render(claim);
  assert.match(html, /<details[^>]*><summary[^>]*>Technical diagnostics \(5\)/);
  assert.doesNotMatch(html, /<details[^>]*\bopen\b/);
  for (const code of oldCodes) assert.ok(html.includes(code), code);
  assert.equal(JSON.stringify(claim), before);
});

test("neutral evidence explains the score and stays outside decisive evidence", () => {
  const claim = makeReport("support").claims[0];
  const html = renderToStaticMarkup(React.createElement(ArticleEvidenceDetails, { claim }));
  assert.match(html, /Not used as decisive evidence/);
  assert.match(html, /neutral · NLI score 0.91/);
  assert.match(html, /This passage neither supports nor refutes the claim/);
});

test("failed, unavailable and skipped execution cannot display reviewed success notes", () => {
  for (const state of ["FAILED", "UNAVAILABLE", "SKIPPED_LIMIT"]) {
    const claim = makeReport("support").claims[0];
    claim.execution_status = state;
    const html = render(claim);
    assert.doesNotMatch(html, /Reviewed cross-source support applies/);
    assert.match(html, state === "FAILED" ? /could not be assessed/ : state === "UNAVAILABLE" ? /assessment was unavailable/ : /claim was skipped/);
  }
});
