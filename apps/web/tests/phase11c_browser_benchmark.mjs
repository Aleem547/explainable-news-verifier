/**
 * Phase 11C.3: authenticated, sequential verification benchmark.
 *
 * Use Chrome signed in normally, then restart that dedicated Chrome profile
 * with localhost-only remote debugging and attach via Playwright CDP.
 * NEVER automate Google sign-in or use your everyday Chrome profile.
 *
 * Run from apps/web:
 *   node tests/phase11c_browser_benchmark.mjs --runs 1
 *   node tests/phase11c_browser_benchmark.mjs --runs 5
 */
import { chromium, expect } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { performance } from 'node:perf_hooks';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const WEB_ORIGIN = 'http://localhost:3000';
const CDP_ENDPOINT = 'http://127.0.0.1:9237';
const CLAIM = 'The Eiffel Tower is located in Berlin, Germany.';
const EXPECTED_VERDICT = 'REFUTING_EVIDENCE';
const EVIDENCE_LIMIT = 5;
const API_PATH = '/api/verification';
const MAX_RUNS = 20;
const RESPONSE_TIMEOUT_MS = 150_000;
const BETWEEN_RUNS_MS = 2_000;

function readRuns(args) {
  if (args.length !== 2 || args[0] !== '--runs') {
    throw new Error('Usage: node tests/phase11c_browser_benchmark.mjs --runs 1');
  }
  const runs = Number(args[1]);
  if (!Number.isInteger(runs) || runs < 1 || runs > MAX_RUNS) {
    throw new Error(`--runs must be an integer between 1 and ${MAX_RUNS}`);
  }
  return runs;
}

function round(value) {
  return Number.isFinite(value) ? Math.round(value * 1000) / 1000 : null;
}

function statistics(values) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  const percentile = (p) =>
    sorted.length ? round(sorted[Math.ceil(sorted.length * p / 100) - 1]) : null;
  return {
    count: sorted.length,
    mean_ms: sorted.length
      ? round(sorted.reduce((sum, value) => sum + value, 0) / sorted.length)
      : null,
    min_ms: sorted.length ? round(sorted[0]) : null,
    p50_ms: percentile(50),
    p90_ms: percentile(90),
    p95_ms: percentile(95),
    max_ms: sorted.length ? round(sorted.at(-1)) : null,
    percentile_method: 'nearest-rank',
  };
}

function csvValue(value) {
  return `"${String(value ?? '').replaceAll('"', '""')}"`;
}

async function saveResults(startedUtc, requestedRuns, records, fatalError) {
  const webDirectory = fileURLToPath(new URL('../', import.meta.url));
  const outputDirectory = path.resolve(webDirectory, '../../benchmarks/results');
  await mkdir(outputDirectory, { recursive: true });
  const stamp = startedUtc.replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');
  const prefix = path.join(outputDirectory, `phase11c_browser_${stamp}`);
  const successful = records.filter((record) => record.ok);
  const statuses = {};
  for (const record of records) {
    const key = String(record.http_status ?? 'no-response');
    statuses[key] = (statuses[key] ?? 0) + 1;
  }
  const summary = {
    attempted: records.length,
    successful: successful.length,
    failed: records.length - successful.length,
    http_status_counts: statuses,
    browser_latency: statistics(successful.map((r) => r.browser_ms)),
    backend_latency: statistics(successful.map((r) => r.backend_ms)),
  };
  const report = {
    schema_version: 3,
    phase: '11C.3',
    scenario: 'Authenticated sequential Chrome-over-CDP verification',
    started_utc: startedUtc,
    finished_utc: new Date().toISOString(),
    website_origin: WEB_ORIGIN,
    requested_runs: requestedRuns,
    claim_length: CLAIM.length,
    evidence_limit: EVIDENCE_LIMIT,
    expected_verdict: EXPECTED_VERDICT,
    fatal_error: fatalError,
    summary,
    records,
    notes: [
      'Real application login and quotas remain enforced.',
      'Never store CDP credentials, cookies, sessions, or user identifiers in reports.',
      'Browser timings include local web UI and proxy overhead, not only inference.',
      'Five requests are insufficient for reliable tail-latency or capacity estimates.',
    ],
  };
  const columns = [
    'run', 'timestamp_utc', 'http_status', 'ok', 'verdict', 'browser_ms',
    'backend_ms', 'retrieved_count', 'assessed_count', 'error_code', 'error',
  ];
  const csv = [
    columns.join(','),
    ...records.map((record) => columns.map((key) => csvValue(record[key])).join(',')),
  ].join('\n') + '\n';
  await writeFile(`${prefix}.json`, JSON.stringify(report, null, 2) + '\n', 'utf8');
  await writeFile(`${prefix}_requests.csv`, csv, 'utf8');
  console.log('\n--- Benchmark report ---');
  console.log('JSON:', `${prefix}.json`);
  console.log('CSV:', `${prefix}_requests.csv`);
  console.log(`Completed: ${summary.successful}/${summary.attempted}`);
  console.log('HTTP statuses:', JSON.stringify(statuses));
  console.log('Browser latency:', JSON.stringify(summary.browser_latency));
  console.log('Backend latency:', JSON.stringify(summary.backend_latency));
  return summary;
}

async function authenticatedSession(page) {
  // No cookie, token, email, account ID or name ever leaves this page.
  const check = await page.evaluate(async () => {
    const response = await fetch('/api/auth/session', {
      credentials: 'same-origin',
      cache: 'no-store',
    });
    const session = await response.json().catch(() => null);
    return {
      status: response.status,
      hasUserId: typeof session?.user?.id === 'string' && session.user.id.length > 0,
    };
  });
  console.log(`Session HTTP: ${check.status}; User ID exists: ${check.hasUserId}`);
  return check.status === 200 && check.hasUserId;
}

async function verifyOnce(page, run) {
  const result = {
    run,
    timestamp_utc: new Date().toISOString(),
    http_status: null,
    ok: false,
    verdict: null,
    browser_ms: null,
    backend_ms: null,
    retrieved_count: null,
    assessed_count: null,
    error_code: null,
    error: null,
  };
  console.log(`\nRun ${run} ...`);
  try {
    if (!(await authenticatedSession(page))) {
      result.error_code = 'AUTH_SESSION_MISSING';
      throw new Error('Session expired before verification. No request sent.');
    }
    const textarea = page.locator('textarea').first();
    await textarea.fill(CLAIM);
    const selector = page.locator('select').first();
    if (!(await selector.count())) throw new Error('Evidence selector missing.');
    await selector.selectOption({ label: `${EVIDENCE_LIMIT} passages` });

    const button = page.getByRole('button', { name: /verify claim/i });
    if (!(await button.isEnabled())) {
      await textarea.fill('');
      await textarea.fill(CLAIM);
    }
    await expect(button).toBeEnabled({ timeout: 10_000 });

    const started = performance.now();
    const [response] = await Promise.all([
      page.waitForResponse(
        (candidate) => {
          const url = new URL(candidate.url());
          return url.origin === WEB_ORIGIN && url.pathname === API_PATH &&
            candidate.request().method() === 'POST';
        },
        { timeout: RESPONSE_TIMEOUT_MS },
      ),
      button.click({ timeout: 15_000 }),
    ]);
    result.http_status = response.status();
    const body = await response.json().catch(() => null);
    result.browser_ms = round(performance.now() - started);
    if (body && typeof body === 'object' && !Array.isArray(body)) {
      result.verdict = typeof body.verdict === 'string' ? body.verdict : null;
      result.backend_ms = round(body.latency_ms);
      result.retrieved_count = Number.isInteger(body.retrieved_count)
        ? body.retrieved_count : null;
      result.assessed_count = Number.isInteger(body.assessed_count)
        ? body.assessed_count : null;
      result.error_code = typeof body.code === 'string' ? body.code : null;
    }
    result.ok = result.http_status === 200 &&
      result.verdict === EXPECTED_VERDICT && result.backend_ms !== null;
    if (!result.ok) {
      result.error = `Unexpected status/verdict: ${result.http_status} / ${result.verdict ?? 'none'}`;
    }
    console.log(`HTTP ${result.http_status}; verdict=${result.verdict ?? '-'}; ` +
      `browser=${result.browser_ms}ms; backend=${result.backend_ms ?? '-'}ms`);
    if (result.error_code) console.log('Error code:', result.error_code);
  } catch (error) {
    result.error = error instanceof Error ? error.message.slice(0, 250) : 'Unknown error';
    console.error('Run failed:', result.error);
  }
  return result;
}

async function main() {
  const requestedRuns = readRuns(process.argv.slice(2));
  const startedUtc = new Date().toISOString();
  const records = [];
  let fatalError = null;
  let browser;
  let page;
  try {
    console.log(`Phase 11C.3 — ${requestedRuns} sequential authenticated runs`);
    console.log('Connecting to a dedicated Google Chrome profile signed in earlier.');
    console.log(`CDP endpoint: ${CDP_ENDPOINT}`);
    browser = await chromium.connectOverCDP(CDP_ENDPOINT, { timeout: 15_000 });
    const context = browser.contexts()[0];
    if (!context) throw new Error('Chrome has no default browser context.');
    page = await context.newPage();
    await page.goto(`${WEB_ORIGIN}/verify`, { waitUntil: 'load', timeout: 30_000 });
    await page.locator('textarea').first().waitFor({ state: 'visible', timeout: 20_000 });
    await page.getByRole('button', { name: /verify claim/i })
      .waitFor({ state: 'visible', timeout: 20_000 });

    if (!(await authenticatedSession(page))) {
      throw new Error(
        'This Chrome testing profile is not signed in. ' +
        'Close the debug Chrome window, run the Login step, and try again.'
      );
    }
    console.log('Authenticated preflight PASSED.');
    for (let run = 1; run <= requestedRuns; run++) {
      const outcome = await verifyOnce(page, run);
      records.push(outcome);
      if (!outcome.ok) {
        console.log('Stopped after failure; no automatic retries or quota bypass.');
        break;
      }
      if (run < requestedRuns) await page.waitForTimeout(BETWEEN_RUNS_MS);
    }
  } catch (error) {
    fatalError = error instanceof Error ? error.message.slice(0, 250) : 'Unknown error';
    console.error('Benchmark stopped:', fatalError);
  } finally {
    try { if (page && !page.isClosed()) await page.close(); } catch { /* best effort */ }
    // Disconnects Playwright. Leave Chrome open until you close its window.
    try { if (browser) await browser.close(); } catch { /* best effort */ }
    const summary = await saveResults(startedUtc, requestedRuns, records, fatalError);
    if (fatalError || summary.successful !== requestedRuns) process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
