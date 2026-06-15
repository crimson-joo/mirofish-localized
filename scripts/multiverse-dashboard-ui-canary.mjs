#!/usr/bin/env node
/** Multiverse dashboard UI canary.
 * Verifies that the product-facing comparison card and Report Agent controls are
 * present in source and production build artifacts. Pair with browser preview in
 * release QA for a visual check.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const viewPath = path.join(root, 'frontend/src/views/MultiverseDashboardView.vue')
const apiPath = path.join(root, 'frontend/src/api/simulation.js')
const distDir = path.join(root, 'frontend/dist')

const requiredSource = [
  'data-testid="multiverse-comparison-panel"',
  '단일 실행 대비 개선 판단',
  '보고서 AI(Report Agent)에게 묻기',
  'compareMultiverseWithSingle',
  'chatMultiverseReportAgent',
  'contextualSuggestedQuestions',
  '비교 기준'
]
const requiredApi = [
  '/compare-single',
  '/report-agent-chat'
]

function assertContains(label, text, needles) {
  const missing = needles.filter((needle) => !text.includes(needle))
  if (missing.length) {
    throw new Error(`${label} missing markers: ${missing.join(', ')}`)
  }
}

const source = fs.readFileSync(viewPath, 'utf8')
const api = fs.readFileSync(apiPath, 'utf8')
assertContains('MultiverseDashboardView.vue', source, requiredSource)
assertContains('simulation.js', api, requiredApi)

const distIndex = path.join(distDir, 'index.html')
if (!fs.existsSync(distIndex)) {
  throw new Error('frontend/dist/index.html missing; run npm run build first')
}
const assets = fs.readdirSync(path.join(distDir, 'assets')).filter((name) => name.endsWith('.js') || name.endsWith('.css'))
const bundleText = assets.map((name) => fs.readFileSync(path.join(distDir, 'assets', name), 'utf8')).join('\n')
assertContains('production bundle', bundleText, [
  '단일 실행 대비 개선 판단',
  '보고서 AI(Report Agent)에게 묻기',
  'compare-single',
  'report-agent-chat'
])

const result = {
  status: 'PASS',
  checked_at: new Date().toISOString(),
  source_markers: requiredSource.length,
  api_markers: requiredApi.length,
  bundle_assets_checked: assets.length,
}
console.log(JSON.stringify(result, null, 2))
