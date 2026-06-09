#!/usr/bin/env node
/**
 * Local-runtime browser canary for Hermes webhook runs.
 *
 * This verifies the actual local Vite app from a browser user's perspective.
 * It intentionally runs outside GitHub Actions because the app runtime lives on
 * the user's Mac, not on the Actions runner.
 */

import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'

const root = process.cwd()
const frontendUrl = process.argv[2] || process.env.FRONTEND_URL || 'http://127.0.0.1:3000/'
const backendUrl = process.argv[3] || process.env.BACKEND_URL || 'http://127.0.0.1:5001'
const artifactDir = process.env.CANARY_ARTIFACT_DIR || path.join(root, 'canary-artifacts')

function loadPlaywright() {
  const candidates = [
    path.join(root, 'node_modules', 'playwright', 'package.json'),
    path.join(root, 'frontend', 'node_modules', 'playwright', 'package.json'),
    path.join(root, 'frontend', 'node_modules', 'playwright-core', 'package.json'),
  ]
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      const requireFromCandidate = createRequire(pathToFileURL(candidate))
      return requireFromCandidate(candidate.includes('playwright-core') ? 'playwright-core' : 'playwright')
    }
  }
  const requireFromRoot = createRequire(pathToFileURL(path.join(root, 'package.json')))
  return requireFromRoot('playwright')
}

const { chromium } = loadPlaywright()

const scenarios = {
  ko: {
    must: ['보고서를 업로드하고', '미래를 예측하세요', 'GitHub 페이지 방문'],
    forbidden: ['上传任意报告', 'Predict the Future'],
  },
  en: {
    must: ['Upload Reports', 'Predict the Future', 'Visit our Github page'],
    forbidden: ['보고서를 업로드하고', '上传任意报告'],
  },
  zh: {
    must: ['上传任意报告', '即刻推演未来', '访问我们的Github主页'],
    forbidden: ['보고서를 업로드하고', 'Predict the Future'],
  },
}

async function checkHealth() {
  const response = await fetch(`${backendUrl.replace(/\/$/, '')}/health`)
  if (!response.ok) throw new Error(`backend health failed: ${response.status}`)
  return response.json()
}

async function run() {
  fs.mkdirSync(artifactDir, { recursive: true })
  const health = await checkHealth()
  const browser = await chromium.launch({ headless: true })
  const results = []

  try {
    for (const [locale, expectation] of Object.entries(scenarios)) {
      const context = await browser.newContext({ viewport: { width: 1365, height: 1200 } })
      const consoleErrors = []
      await context.addInitScript((loc) => {
        window.localStorage.setItem('locale', loc)
      }, locale)
      const page = await context.newPage()
      page.on('console', (msg) => {
        if (msg.type() === 'error') consoleErrors.push(msg.text())
      })
      page.on('pageerror', (err) => consoleErrors.push(err.message))

      const response = await page.goto(frontendUrl, { waitUntil: 'networkidle', timeout: 60000 })
      if (!response || !response.ok()) {
        throw new Error(`${locale} navigation failed: ${response && response.status()}`)
      }

      const text = await page.locator('body').innerText({ timeout: 15000 })
      const lang = await page.evaluate(() => document.documentElement.lang)
      const title = await page.title()
      if (lang !== locale) throw new Error(`${locale} html lang mismatch: ${lang}`)
      for (const marker of expectation.must) {
        if (!text.includes(marker)) throw new Error(`${locale} missing marker: ${marker}`)
      }
      for (const marker of expectation.forbidden) {
        if (text.includes(marker)) throw new Error(`${locale} leaked marker: ${marker}`)
      }
      if (consoleErrors.length) {
        throw new Error(`${locale} browser console errors: ${consoleErrors.join('\n')}`)
      }

      const screenshot = path.join(artifactDir, `local-runtime-locale-${locale}.png`)
      await page.screenshot({ path: screenshot, fullPage: true })
      await context.close()
      results.push({ locale, lang, title, screenshot })
      console.log(`BROWSER LOCALE CANARY PASS ${locale} ${screenshot}`)
    }
  } finally {
    await browser.close()
  }

  const summary = { frontendUrl, backendUrl, health, results }
  const summaryPath = path.join(artifactDir, 'local-runtime-browser-canary.json')
  fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2))
  console.log(`SUMMARY ${summaryPath}`)
}

run().catch((err) => {
  console.error(err)
  process.exit(1)
})
