// 构建后生成 sitemap.xml 与 robots.txt，提升站点可发现性。
// 在 package.json 的 docs:build 中串接执行：vitepress build docs && node tools/gen_sitemap.mjs
import fs from 'node:fs'
import path from 'node:path'

const SITE_BASE = 'https://maicarons.github.io/duckdb-book/'
const DIST = path.resolve('docs/.vitepress/dist')

function walk(dir, out = []) {
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name)
    const stat = fs.statSync(full)
    if (stat.isDirectory()) walk(full, out)
    else if (name.endsWith('.html')) out.push(full)
  }
  return out
}

function toUrl(file) {
  let rel = path.relative(DIST, file).split(path.sep).join('/')
  rel = rel.replace(/\.html$/, '')
  if (rel === 'index') rel = ''
  // cleanUrls: 去掉末尾 /index
  rel = rel.replace(/\/index$/, '')
  return SITE_BASE + rel
}

function main() {
  if (!fs.existsSync(DIST)) {
    console.error('[sitemap] dist 不存在，跳过（可能未先 build）')
    process.exit(0)
  }
  const htmlFiles = walk(DIST).filter((f) => !path.basename(f).startsWith('404'))
  const urls = [...new Set(htmlFiles.map(toUrl))].sort()

  const body = urls
    .map((u) => `  <url>\n    <loc>${u}</loc>\n    <changefreq>weekly</changefreq>\n  </url>`)
    .join('\n')

  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${body}\n</urlset>\n`

  fs.writeFileSync(path.join(DIST, 'sitemap.xml'), xml)
  fs.writeFileSync(
    path.join(DIST, 'robots.txt'),
    `User-agent: *\nAllow: /\nSitemap: ${SITE_BASE}sitemap.xml\n`
  )
  console.log(`[sitemap] 生成 ${urls.length} 条 URL -> sitemap.xml / robots.txt`)
}

main()
