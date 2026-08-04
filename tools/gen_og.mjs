// 把社交分享卡 SVG 渲染为 1200x630 PNG（og:image / twitter:image）。
// 依赖 @resvg/resvg-js（WASM 渲染，无系统级原生依赖）。
// 在 package.json 的 docs:build 中串接：vitepress build && node tools/gen_sitemap.mjs && node tools/gen_og.mjs
import fs from 'node:fs'
import path from 'node:path'
import { Resvg } from '@resvg/resvg-js'

const ROOT = process.cwd()
const SRC = path.join(ROOT, 'tools', 'social-card.svg')
const OUT = path.join(ROOT, 'docs', 'public', 'og-image.png')

function main() {
  if (!fs.existsSync(SRC)) {
    console.error('[og] 缺少 tools/social-card.svg，跳过')
    process.exit(0)
  }
  const svg = fs.readFileSync(SRC, 'utf-8')
  const resvg = new Resvg(svg, {
    fitTo: { mode: 'width', value: 1200 },
  })
  const png = resvg.render().asPng()
  fs.writeFileSync(OUT, png)
  console.log(`[og] 生成社交分享图 ${png.length} bytes -> og-image.png`)
}

main()
