# Liquid Glass

Midiary uses the imperative DOM API from [Glass-HQ/liquid-glass](https://github.com/Glass-HQ/liquid-glass), pinned to commit `8795d30e2519e7e33b26e19281b9ad26b5eed229` (SDK 0.0.1).

The production bundle, stylesheet and map encoder worker are served from `static/vendor/liquid-glass`. Runtime requests stay on this site's origin. The renderer refracts the local faculty illustration in a separate decorative layer. Real cards, text, buttons and settings menus keep their existing layout and handlers. At most ten visible surfaces are registered; scrolling and page navigation remove surfaces that leave the viewport.

HTTPS, WebGPU and a suitable adapter are required. Safari and iOS browsers keep the existing theme because this SDK release documents WebKit rendering issues. Missing WebGPU, rendering errors, reduced transparency, forced colors and data saving also retain the existing theme. Reduced motion disables SDK motion; rendering stops while the page is hidden.

To rebuild, install Bun 1.4.2, clone the repository outside the application directory, and use its pinned lockfile:

```sh
git clone https://github.com/Glass-HQ/liquid-glass.git /path/to/liquid-glass
git -C /path/to/liquid-glass checkout 8795d30e2519e7e33b26e19281b9ad26b5eed229
cd /path/to/liquid-glass
bun install --frozen-lockfile --ignore-scripts --filter @glass-sdk/liquid-glass
bun run --cwd packages/liquid-glass build
cd /root/systemfgu
bun scripts/build-liquid-glass.mjs /path/to/liquid-glass
chmod 755 static/vendor static/vendor/liquid-glass
chmod 644 static/vendor/liquid-glass/* static/liquid-glass.css
```

The build checks the commit and copies licenses for every bundled third-party package. `provenance.json` records the upstream revision and dependency versions. No Node or Bun runtime is needed by the production server.
