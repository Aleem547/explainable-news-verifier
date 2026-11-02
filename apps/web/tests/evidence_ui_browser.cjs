/* eslint-disable @typescript-eslint/no-require-imports -- Local Playwright checks. */
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { chromium, expect } = require("@playwright/test");
const { makeReport, oldCodes } = require("./evidence_ui_fixture.cjs");

(async () => {
  const output = process.env.EVIDENCE_UI_QA_DIR || path.resolve(__dirname, "../../../evidence-ui-qa");
  const base = process.env.EVIDENCE_UI_QA_URL || "http://127.0.0.1:4334";
  assert.equal(new URL(base).hostname, "127.0.0.1");
  await fs.mkdir(output, { recursive: true });
  const root = path.resolve(__dirname, "..");
  const server = spawn(process.execPath, [path.join(root, "node_modules/next/dist/bin/next"), "start",
    "--hostname", "127.0.0.1", "--port", new URL(base).port], {
    cwd: root, env: { ...process.env, ARTICLE_VERIFICATION_ENABLED: "true", AUTH_TRUST_HOST: "true",
      AUTH_SECRET: "local-evidence-ui-test-only", NEXT_TELEMETRY_DISABLED: "1" }, stdio: "ignore",
  });
  let browser;
  const names = [];
  const errors = [];
  try {
    for (let attempt = 0; ; attempt++) {
      try { if ((await fetch(base)).ok) break; } catch {}
      assert.ok(attempt < 100 && server.exitCode === null, "Local production server did not start");
      await new Promise(resolve => setTimeout(resolve, 200));
    }
    browser = await chromium.launch({ headless: true, args: ["--no-sandbox"],
      ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}) });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on("pageerror", error => errors.push(error.message));
    let state = "support", requests = 0;
    await page.route("**/api/article-verification", async route => {
      requests++;
      assert.equal(route.request().method(), "POST");
      const body = route.request().postDataJSON();
      assert.equal(body.kind, "pasted");
      assert.ok(body.text.startsWith("Chandrayaan-3 landed on the Moon."));
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(makeReport(state)) });
    });
    await page.goto(base);
    await expect(page.getByText("Claim-specific external checks", { exact: true })).toBeVisible();
    await expect(page.getByText("Independent corroboration pending", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Log in", exact: true })).toBeVisible();
    await page.screenshot({ path: path.join(output, "homepage-desktop.png"), fullPage: true });
    names.push("homepage_replaces_blanket_pending_notice_with_claim_scoped_coverage");

    await page.goto(base + "/article");
    const sample = page.getByRole("button", { name: "Chandrayaan-3 landed on the Moon.", exact: true });
    await expect(sample).toBeEnabled();
    await sample.click();
    await expect(page.locator("#article-text")).toHaveValue(/Chandrayaan-3 landed on the Moon\./);
    assert.equal(requests, 0);
    names.push("moon_example_preserved_without_automatic_submission");
    const submit = page.getByRole("button", { name: "Verify article preview", exact: true });
    await submit.click();
    const notes = page.getByRole("region", { name: "Evidence notes", exact: true });
    await expect(notes).toContainText("Reviewed cross-source support applies only to this claim");
    await expect(page.getByText("Independent factual corroboration not established. Article-wide truth verdict unavailable.", { exact: true })).toHaveCount(0);
    await expect(page.getByText("This passage neither supports nor refutes the claim. Its score is confidence in that textual relation.", { exact: true })).toBeVisible();
    for (const code of oldCodes) await expect(notes.getByText(code, { exact: true })).not.toBeVisible();
    await page.getByRole("region", { name: "Article evidence report", exact: true }).screenshot({ path: path.join(output, "article-desktop.png") });
    names.push("reviewed_result_and_neutral_passage_have_clear_noncontradictory_labels");

    await notes.getByText("Technical diagnostics (5)", { exact: true }).click();
    for (const code of oldCodes) await expect(notes.getByText(code, { exact: true })).toBeVisible();
    names.push("every_original_and_unknown_warning_code_can_be_expanded");

    for (const item of [
      ["pending", "Reviewed cross-source corroboration is not established for this claim"],
      ["unavailable", "Reviewed cross-source corroboration is not established for this claim"],
      ["conflicting", "The admitted evidence contains both support and refutation"],
      ["insufficient", "The stored external evidence is insufficient for this claim"],
      ["refute", "Reviewed cross-source refutation applies only to this claim"],
    ]) {
      state = item[0];
      await submit.click();
      await expect(notes).toContainText(item[1]);
      await expect(notes.getByText(oldCodes[0], { exact: true })).not.toBeVisible();
    }
    names.push("pending_unavailable_conflicting_insufficient_and_refuting_results_remain_distinct");

    await page.setViewportSize({ width: 320, height: 850 });
    state = "support";
    await submit.click();
    await expect(notes).toContainText("Reviewed cross-source support applies only");
    await notes.getByText("Technical diagnostics (5)", { exact: true }).click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    for (const code of oldCodes) await expect(notes.getByText(code, { exact: true })).toBeVisible();
    await notes.scrollIntoViewIfNeeded();
    await notes.screenshot({ path: path.join(output, "article-mobile-diagnostics.png") });
    await notes.getByText("Technical diagnostics (5)", { exact: true }).click();
    await page.getByRole("region", { name: "Article evidence report", exact: true }).screenshot({ path: path.join(output, "article-mobile.png") });
    names.push("mobile_320px_diagnostics_remain_readable_without_horizontal_overflow");
    await page.goto(base);
    await expect(page.getByText("Claim-specific external checks", { exact: true })).toBeVisible();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    names.push("mobile_homepage_coverage_notice_fits_without_horizontal_overflow");
    assert.deepEqual(errors, []);
    const result = { status: "EVIDENCE_UI_BROWSER_CHECKS_PASSED", checks: names.length, names,
      production_build: true, backend_requests: "local mocked responses only", production_deployment_performed: false };
    await fs.writeFile(path.join(output, "RESULT.json"), JSON.stringify(result, null, 2) + "\n");
    console.log(JSON.stringify(result, null, 2));
  } finally { if (browser) await browser.close(); server.kill("SIGTERM"); }
})().catch(error => { console.error(error); process.exitCode = 1; });
