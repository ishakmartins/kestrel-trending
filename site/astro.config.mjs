import fs from 'node:fs';
import { defineConfig } from 'astro/config';

// Repo has no CNAME / custom domain configured — GitHub Pages serves this
// as a standard project page at https://ishakmartins.github.io/kestrel-trending/.
const base = '/kestrel-trending';

// dev only: `astro dev` serves public/ verbatim and never resolves <dir>/ to index.html,
// so the staged dashboard 404s locally even though the built site serves it fine.
const publicDirIndex = {
  name: 'public-dir-index',
  configureServer(server) {
    server.middlewares.use((req, _res, next) => {
      // astro may or may not have stripped `base` by now, so look up without it
      // but keep whatever prefix the request arrived with
      const [path, query] = req.url.split('?');
      const dir = path.replace(/\/$/, '');
      if (fs.existsSync(new URL('./public' + dir.replace(base, '') + '/index.html', import.meta.url))) {
        req.url = dir + '/index.html' + (query ? '?' + query : '');
      }
      next();
    });
  },
};

export default defineConfig({
  site: 'https://ishakmartins.github.io',
  base,
  outDir: '../docs',
  trailingSlash: 'ignore',
  build: { format: 'directory' },
  vite: { plugins: [publicDirIndex] },
});
