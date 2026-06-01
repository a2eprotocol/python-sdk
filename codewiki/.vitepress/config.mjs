import { withMermaid } from "vitepress-plugin-mermaid"
import sidebar from "./sidebar.mjs"
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Reconstruct __dirname for ES modules (.mjs files)
const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

function getSvgDataUrl(relativePath) {
  const absolutePath = path.resolve(__dirname, relativePath)
  const base64String = fs.readFileSync(absolutePath, 'base64').replace(/[\r\n]+/g, '')
  return `data:image/svg+xml;base64,${base64String}`
}

const logoLight = getSvgDataUrl('../assets/logo-light.svg')
const logoDark = getSvgDataUrl('../assets/logo-dark.svg')

export default withMermaid({
  title: 'A2E Protocol',
  description: 'Agent-to-Environment Protocol — Python SDK Documentation & Protocol Specification',
  base: '/docs/',
  themeConfig: {
    logo: {
      light: logoLight,
      dark: logoDark,
      alt: 'A2E'
    },
    nav: [
      { text: 'Home', link: '/' },
      { text: 'SDK Reference', link: '/sdk-reference/client-api' },
      { text: 'Protocol Spec', link: '/protocol-spec/message-format' },
      { text: 'Cookbook', link: '/cookbook/writing-a-plugin' },
      { text: 'Blog', link: '/blog/2026-05-21-the-harness-is-the-product' }
    ],
    sidebar: sidebar,
    socialLinks: [
      { icon: 'github', link: 'https://github.com/a2eprotocol/python-sdk' }
    ],
    footer: {
      message: 'A2E Protocol v1.0 — Released under the MIT License.',
      copyright: 'Copyright 2026 Cynepia Technologies'
    },
    search: {
      provider: 'local'
    },
    editLink: {
      pattern: 'https://github.com/a2eprotocol/a2e/edit/main/codewiki/:path',
      text: 'Edit this page on GitHub'
    }
  },
  mermaid: {
    startOnLoad: true
  },
  mermaidConfig: {
    theme: "dark"
  }
})
