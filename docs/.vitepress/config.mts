import { defineConfig } from 'vitepress'
import { fileURLToPath } from 'node:url'
import { dirname, resolve, join } from 'node:path'
import fs from 'node:fs'

const __dirname = dirname(fileURLToPath(import.meta.url))
const docsDir = resolve(__dirname, '..')
const chaptersDir = join(docsDir, 'chapters')
const referenceDir = join(docsDir, 'reference')

function titleOf(file: string): string {
  const txt = fs.readFileSync(file, 'utf-8')
  const m = txt.match(/^#\s+(.+)$/m)
  return m ? m[1].trim() : ''
}

// strip zero-padding: "第 01 章" -> "第 1 章"
function shortTitle(file: string): string {
  return titleOf(file).replace(/^第\s*0?(\d+)\s*章\s*/, '第 $1 章 ')
}

// 7 parts -> chapter numbers (per parameter_card.md)
const parts = [
  { text: '第一部分 基础入门', items: [1, 2, 3, 4, 5, 6] },
  { text: '第二部分 数据工程', items: [7, 8] },
  { text: '第三部分 客户端与生态集成', items: [9, 10, 11, 12] },
  { text: '第四部分 扩展机制', items: [13, 14] },
  { text: '第五部分 性能与运维', items: [15, 16] },
  { text: '第六部分 原理剖析', items: [17] },
  { text: '第七部分 实战与总结', items: [18, 19] },
]

const bookSidebar = parts.map((p) => ({
  text: p.text,
  collapsed: false,
  items: p.items.map((n) => ({
    text: shortTitle(join(chaptersDir, `chapter${String(n).padStart(2, '0')}.md`)),
    link: `/chapters/chapter${String(n).padStart(2, '0')}`,
  })),
}))

const refItems = fs
  .readdirSync(referenceDir)
  .filter((f) => f.endsWith('.md'))
  .sort()
  .map((f) => ({
    text: titleOf(join(referenceDir, f)),
    link: `/reference/${f.replace(/\.md$/, '')}`,
  }))

const sidebar = [
  {
    text: '开始阅读',
    items: [
      { text: '前言', link: '/preface' },
      { text: '下载与资源', link: '/downloads' },
    ],
  },
  ...bookSidebar,
  { text: '参考资料（官方文档研读）', items: refItems },
]

const refNav = refItems.map((r) => ({ text: r.text, link: r.link }))

export default defineConfig({
  base: '/duckdb-book/',
  lang: 'zh-CN',
  title: 'DuckDB 数据库从入门到进阶',
  description:
    '基于 DuckDB v1.5.5 官方文档的系统性实战指南：进程内、列式、向量化的分析型数据库，从入门到进阶。',
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/duckdb-book/favicon.svg' }],
    ['meta', { name: 'keywords', content: 'DuckDB, 数据库, OLAP, 列式存储, 向量化, 数据分析, 嵌入式数据库, 教程' }],
    ['meta', { name: 'og:type', content: 'website' }],
    ['meta', { name: 'og:locale', content: 'zh_CN' }],
    ['meta', { name: 'og:title', content: 'DuckDB 数据库从入门到进阶' }],
    ['meta', { name: 'og:description', content: '基于 DuckDB v1.5.5 官方文档的系统性实战指南：从入门到进阶的进程内分析型数据库教程。' }],
    ['meta', { name: 'og:url', content: 'https://maicarons.github.io/duckdb-book/' }],
    ['meta', { name: 'og:site_name', content: 'DuckDB 数据库从入门到进阶' }],
    ['meta', { name: 'og:image', content: 'https://maicarons.github.io/duckdb-book/og-image.png' }],
    ['meta', { name: 'og:image:width', content: '1200' }],
    ['meta', { name: 'og:image:height', content: '630' }],
    ['meta', { name: 'og:image:alt', content: 'DuckDB 数据库从入门到进阶 — 基于官方文档 v1.5.5 的系统性实战指南' }],
    ['meta', { name: 'twitter:card', content: 'summary_large_image' }],
    ['meta', { name: 'twitter:image', content: 'https://maicarons.github.io/duckdb-book/og-image.png' }],
    ['meta', { name: 'twitter:image:alt', content: 'DuckDB 数据库从入门到进阶' }],
  ],
  lastUpdated: true,
  cleanUrls: true,
  build: {
    // VitePress 本地搜索索引较大，属正常现象；上调阈值消除构建噪音
    chunkSizeWarningLimit: 3000,
  },
  editLink: {
    pattern: 'https://github.com/Maicarons/duckdb-book/edit/main/docs/:path',
    text: '在 GitHub 上编辑此页',
  },
  themeConfig: {
    nav: [
      { text: '首页', link: '/' },
      { text: '前言', link: '/preface' },
      { text: '分章阅读', link: '/chapters/chapter01' },
      { text: '参考资料', items: refNav },
      { text: '下载', link: '/downloads' },
    ],
    sidebar,
    outline: [2, 3],
    docFooter: { prev: true, next: true },
    lastUpdatedText: '最后更新',
    returnToTopLabel: '回到顶部',
    sidebarMenuLabel: '菜单',
    darkModeSwitchLabel: '主题',
    lightModeSwitchTitle: '切换到浅色模式',
    darkModeSwitchTitle: '切换到深色模式',
    search: {
      provider: 'local',
      options: {
        locales: {
          'zh-CN': { placeholder: '搜索文档', noDataText: '无结果', headingDepth: 4 },
        },
      },
    },
    socialLinks: [
      { icon: 'github', link: 'https://github.com/Maicarons/duckdb-book' },
    ],
    footer: {
      message: '基于 DuckDB v1.5.5 官方文档整理 · AI 辅助编撰',
      copyright: 'Copyright © 2026 DuckDB 数据库从入门到进阶 编撰团队',
    },
  },
})
