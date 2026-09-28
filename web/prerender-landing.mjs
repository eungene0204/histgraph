// Put the actual landing content in the delivered HTML. Search and ad review
// clients can follow its document links even when they do not run JavaScript.
import { build } from 'esbuild';
import { createElement } from 'react';
import { renderToString } from 'react-dom/server';
import { readFile, writeFile, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const root = fileURLToPath(new URL('.', import.meta.url));
const output = join(root, `._landing-ssr-${process.pid}.mjs`);
const htmlPath = join(root, 'dist/index.html');
try {
  await build({
    stdin: { contents: "export { default } from './src/Landing.jsx';", resolveDir: root },
    bundle: true, format: 'esm', platform: 'node', jsx: 'automatic',
    packages: 'external', outfile: output, logLevel: 'silent',
  });
  const { default: Landing } = await import(`file://${output}`);
  const html = await readFile(htmlPath, 'utf8');
  const marker = '<div id="root"></div>';
  if (!html.includes(marker)) throw new Error('Landing root marker is missing');
  await writeFile(htmlPath, html.replace(marker, `<div id="root">${renderToString(createElement(Landing))}</div>`));
} finally {
  await rm(output, { force: true });
}
