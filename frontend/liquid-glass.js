import { createGlassScene } from '@glass-sdk/liquid-glass/dom';
import { getMaterialRenderer } from '@glass-sdk/liquid-glass/gpu';

// Refract the local faculty illustration, never a screenshot of personal data.
const host = document.getElementById('fgu-diary-design');
const transparency = matchMedia('(prefers-reduced-transparency: reduce)');
const colors = matchMedia('(forced-colors: active)');
const motion = matchMedia('(prefers-reduced-motion: reduce)');
// The pinned SDK reports blank rendering in WebKit. Keep the existing theme
// there until upstream establishes Safari support, including iOS browsers.
const webkit = /AppleWebKit/.test(navigator.userAgent) && !/(Chrome|Chromium|Edg|OPR)\//.test(navigator.userAgent);
const selectors = '.floating-brand,.fd-telegram,.fd-bottom-nav,.week,.fd-lesson-card,.profile-panel,.rating-overview,.fd-calendar-month';
let scene, layer, content, motif, timer, version = 0, starting = false, pendingStart = false;
let surfaces = new Map();
let key = '';
let frame = 0;
const sizes = new ResizeObserver(() => schedule());
host.addEventListener('midiary:brand-motion', position);

function stop(state = 'unavailable') {
  version++;
  clearTimeout(timer);
  cancelAnimationFrame(frame); frame = 0;
  sizes.disconnect();
  for (const [element, surface] of surfaces) {
    surface.remove();
    surface.proxy.remove();
    element.classList.remove('midiary-glass-target');
  }
  surfaces.clear();
  scene?.dispose();
  scene = undefined;
  layer?.remove();
  layer = undefined;
  host.dataset.liquidGlass = state;
}

function options(element) {
  const radius = parseFloat(getComputedStyle(element).borderTopLeftRadius) || 24;
  return {
    radius, material: element.matches('.fd-telegram,.floating-brand') ? 'clear' : 'regular', appearance: host.dataset.theme || 'dark',
    refraction: innerWidth < 600 ? 22 : 32,
    motion: motion.matches ? 'none' : 'reduced', interactive: false,
  };
}

function refresh() {
  if (!scene) return;
  const nextKey = [host.dataset.theme, host.dataset.faculty, innerWidth < 600, motion.matches].join(':');
  if (key !== nextKey) {
    key = nextKey;
    const background = getComputedStyle(document.body, '::before');
    for (const name of ['backgroundImage', 'backgroundPosition', 'backgroundSize', 'backgroundRepeat', 'opacity', 'filter']) {
      motif.style[name] = background[name];
    }
    // Attribute selectors react to the SDK state without changing the motif
    // that was measured above from the existing faculty theme.
    const body = getComputedStyle(document.body);
    content.style.backgroundColor = body.backgroundColor;
    content.style.backgroundImage = body.backgroundImage;
    for (const [element, surface] of surfaces) {
      surface.remove(); surface.proxy.remove(); sizes.unobserve(element);
      element.classList.remove('midiary-glass-target');
    }
    surfaces.clear();
    host.dataset.liquidGlass = 'loading';
  }
  const visible = [...host.querySelectorAll(selectors)].filter(element => {
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < innerHeight;
  }).slice(0, 10);
  const wanted = new Set(visible);
  for (const [element, surface] of surfaces) {
    if (!wanted.has(element)) {
      surface.remove(); surface.proxy.remove(); sizes.unobserve(element);
      element.classList.remove('midiary-glass-target'); surfaces.delete(element);
    }
  }
  for (const element of visible) {
    if (surfaces.has(element)) continue;
    element.classList.add('midiary-glass-target');
    // Let the SDK clip a decorative surface, never the real card or its menu.
    const proxy = document.createElement('div');
    proxy.className = 'midiary-glass-surface';
    layer.append(proxy);
    const rect = element.getBoundingClientRect();
    Object.assign(proxy.style, { left: rect.left+'px', top: rect.top+'px', width: rect.width+'px', height: rect.height+'px' });
    surfaces.set(element, { proxy, remove: scene.addSurface(proxy, options(element)) });
    sizes.observe(element);
  }
  position();
}

function position() {
  if (!scene || frame) return;
  frame = requestAnimationFrame(() => {
    frame = 0;
    const measured = [...surfaces].map(([element, surface]) => [surface.proxy, element.getBoundingClientRect()]);
    for (const [proxy, rect] of measured) {
      for (const [name, value] of [['left', rect.left], ['top', rect.top], ['width', rect.width], ['height', rect.height]]) {
        const next = value+'px';
        if (proxy.style[name] !== next) proxy.style[name] = next;
      }
    }
  });
}

function schedule() {
  if (!scene) return;
  clearTimeout(timer);
  timer = setTimeout(refresh, 100);
}

async function start() {
  if (!host || scene) return;
  if (starting) { pendingStart = true; return; }
  if (!isSecureContext || !navigator.gpu || webkit || transparency.matches || colors.matches || navigator.connection?.saveData) {
    host.dataset.liquidGlass = 'unavailable';
    return;
  }
  starting = true;
  const generation = ++version;
  try {
    const adapter = await navigator.gpu.requestAdapter();
    if (generation !== version || !adapter || adapter.limits.maxUniformBufferBindingSize < 65536) return;
    // SDK diagnostics report map readiness even when a driver returns an empty
    // readback. Validate actual pixels before replacing the existing surfaces.
    const renderer = await getMaterialRenderer();
    const probe = await renderer.render({ width: 8, height: 8, radius: 4, dpr: 1 });
    const center = ((probe.height + Math.floor(probe.height / 2)) * probe.width + Math.floor(probe.width / 2)) * 4 + 3;
    if (generation !== version || probe.pixels[center] !== 255) return;
    host.dataset.liquidGlass = 'loading';
    layer = document.createElement('div');
    layer.className = 'midiary-glass-scene lg-scene';
    layer.setAttribute('aria-hidden', 'true');
    layer.inert = true;
    content = document.createElement('div');
    content.className = 'midiary-glass-content lg-content';
    motif = document.createElement('div');
    motif.className = 'midiary-glass-motif';
    content.append(motif); layer.append(content);
    document.body.prepend(layer);
    scene = createGlassScene(layer, {
      maxSurfaces: 10,
      onDiagnostic(diagnostic) {
        if (generation !== version) return;
        if (diagnostic.error) {
          // Restore existing surfaces on adapter loss or unsupported rendering.
          queueMicrotask(() => stop());
          return;
        }
        host.dataset.liquidGlass = diagnostic.maps > 0 && diagnostic.maps === diagnostic.surfaces ? 'active' : 'loading';
      },
    });
    scene.setContent(content);
    key = '';
    refresh();
  } catch {
    stop();
  } finally {
    starting = false;
    if (!scene) host.dataset.liquidGlass = 'unavailable';
    const restart = pendingStart;
    pendingStart = false;
    if (restart && !document.hidden) start();
  }
}

if (host) {
  const observer = new MutationObserver(records => {
    if (records.some(record => record.attributeName === 'data-theme' || record.attributeName === 'data-faculty')) refresh();
    else if (records.some(record => record.type === 'childList' || record.attributeName === 'hidden')) schedule();
  });
  observer.observe(host, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-theme', 'data-faculty', 'hidden'] });
  addEventListener('scroll', () => { position(); schedule(); }, { passive: true });
  addEventListener('resize', schedule, { passive: true });
  for (const preference of [transparency, colors]) preference.addEventListener('change', () => {
    if (preference.matches) stop(); else start();
  });
  motion.addEventListener('change', schedule);
  addEventListener('pagehide', () => { stop(); });
  addEventListener('pageshow', () => { start(); });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stop('paused'); else start();
  });
  start();
}
