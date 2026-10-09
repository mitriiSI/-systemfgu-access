// Usage: bun scripts/build-liquid-glass.mjs /path/to/Glass-HQ/liquid-glass
// Build the pinned upstream with its bun.lock before running this command.
import { resolve } from 'node:path';
import { readFile, writeFile, copyFile, readdir, mkdir, chmod } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';

const commit = '8795d30e2519e7e33b26e19281b9ad26b5eed229';
const upstream = resolve(process.argv[2] || '');
if (!process.argv[2] || execFileSync('git', ['-C', upstream, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim() !== commit) {
  throw Error(`Build requires Glass-HQ/liquid-glass at ${commit}`);
}
const root = resolve(import.meta.dirname, '..');
const lib = resolve(upstream, 'packages/liquid-glass');
const outdir = resolve(root, 'static/vendor/liquid-glass');
await mkdir(outdir, { recursive: true });
const build = await Bun.build({
  entrypoints: [resolve(root, 'frontend/liquid-glass.js')], outdir,
  target: 'browser', format: 'esm', minify: true, metafile: true,
  plugins: [{ name: 'pinned-liquid-glass', setup(api) {
    api.onResolve({ filter: /^@glass-sdk\/liquid-glass\/(dom|gpu)$/ }, ({ path }) => ({ path: resolve(lib, `dist/${path.split('/').pop()}.js`) }));
  }}],
});
if (!build.success) throw new AggregateError(build.logs, 'Liquid Glass build failed');
await copyFile(resolve(lib, 'dist/styles.css'), resolve(outdir, 'styles.css'));
for (const name of await readdir(resolve(lib, 'dist'))) {
  if (name.startsWith('map-encoder.worker-') && name.endsWith('.js')) await copyFile(resolve(lib, 'dist', name), resolve(outdir, name));
}
const versions = {};
const notices = ['Glass-HQ/liquid-glass\n' + await readFile(resolve(upstream, 'LICENSE'), 'utf8')];
const folders = new Set();
for (const input of Object.keys(build.metafile.inputs)) {
  const path = resolve(input);
  const marker = '/node_modules/';
  const start = path.lastIndexOf(marker);
  if (start < 0) continue;
  const relative = path.slice(start + marker.length);
  const name = relative.split('/').slice(0, relative.startsWith('@') ? 2 : 1).join('/');
  folders.add(path.slice(0, start + marker.length) + name);
}
for (const folder of [...folders].sort()) {
  const dependency = JSON.parse(await readFile(resolve(folder, 'package.json'), 'utf8'));
  versions[dependency.name] = dependency.version;
  const license = (await readdir(folder)).find(name => /^license(?:\.|$)/i.test(name));
  if (!license) throw Error(`Missing redistribution license: ${dependency.name}`);
  notices.push(`\n\n${dependency.name}@${dependency.version}\n${await readFile(resolve(folder, license), 'utf8')}`);
}
await writeFile(resolve(outdir, 'LICENSES.txt'), notices.join('\n'));
await writeFile(resolve(outdir, 'provenance.json'), JSON.stringify({
  repository: 'https://github.com/Glass-HQ/liquid-glass', commit,
  version: JSON.parse(await readFile(resolve(lib, 'package.json'), 'utf8')).version,
  dependencies: versions, renderer: 'WebGPU/WGSL and explicit DOM content',
}, null, 2) + '\n');
// Static files are served by the unprivileged edge container.
await chmod(resolve(root, 'static/vendor'), 0o755);
await chmod(outdir, 0o755);
for (const entry of await readdir(outdir, { withFileTypes: true })) {
  if (entry.isFile()) await chmod(resolve(outdir, entry.name), 0o644);
}
console.log('Local Liquid Glass bundle built from pinned source');
