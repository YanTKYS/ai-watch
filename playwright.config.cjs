const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests/e2e',
  workers: 1,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  timeout: 30_000,
  expect: { timeout: 5_000 },
  reporter: 'list',
  outputDir: 'test-results',
  use: {
    browserName: 'chromium',
    baseURL: 'http://127.0.0.1:4173',
    viewport: { width: 1280, height: 900 },
    serviceWorkers: 'block',
    // 通常/CIはPlaywright対応版。配布元へ接続できないローカル環境だけ既存Chromiumを指定できる。
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'python3 -m http.server 4173 --bind 127.0.0.1',
    url: 'http://127.0.0.1:4173',
    timeout: 10_000,
    reuseExistingServer: false,
    stderr: 'ignore', // 各GETのアクセスログを抑える。ブラウザの通信は失敗時traceで確認できる。
  },
});
