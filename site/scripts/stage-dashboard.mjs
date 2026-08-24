// Copies pre-built artifacts into public/ before `astro build` — same pattern
// kestrel-reports uses to stage report bundles (scripts/cms.py), just for our
// one Python-generated dashboard instead of many CMS-driven report folders.
import { copyFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const siteRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const repoRoot = path.dirname(siteRoot);

mkdirSync(path.join(siteRoot, 'public', 'trending'), { recursive: true });
copyFileSync(
  path.join(repoRoot, 'dataset', 'trends', 'latest_interactive.html'),
  path.join(siteRoot, 'public', 'trending', 'index.html'),
);
copyFileSync(
  path.join(repoRoot, 'src', 'logo', 'lokentra.dev-logo.svg'),
  path.join(siteRoot, 'public', 'logo.svg'),
);
console.log('Staged dashboard + logo into site/public/');
