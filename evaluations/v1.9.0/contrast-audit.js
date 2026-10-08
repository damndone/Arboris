// Contrast audit for the browser: paste into the page console (or javascript_tool).
// Finishes running CSS transitions first (a hidden browser pane freezes them at
// their start value), skips hidden and disabled elements, and reports every
// visible text whose colour against its composited background is below 4.5:1
// (3:1 for large text).
(() => {
  document.getAnimations().forEach((a) => { try { if (a.effect?.getTiming().iterations !== Infinity) a.finish(); } catch {} });
  const toLin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  function oklchToRgb(L, C, H) {
    const h = (H * Math.PI) / 180, a = C * Math.cos(h), b = C * Math.sin(h);
    const l_ = L + 0.3963377774 * a + 0.2158037573 * b, m_ = L - 0.1055613458 * a - 0.0638541728 * b, s_ = L - 0.0894841775 * a - 1.291485548 * b;
    const l = l_ ** 3, m = m_ ** 3, s = s_ ** 3;
    const lin = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s, -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
    return lin.map((v) => { v = Math.min(1, Math.max(0, v)); return v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055; });
  }
  function parse(str) {
    let m;
    if ((m = str.match(/^rgba?\(([^)]+)\)/))) { const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return { rgb: p.slice(0, 3).map((x) => x / 255), a: p[3] ?? 1 }; }
    if ((m = str.match(/^color\(srgb ([^)]+)\)/))) { const p = m[1].split(/[ /]+/).filter(Boolean).map(Number); return { rgb: p.slice(0, 3), a: p[3] ?? 1 }; }
    if ((m = str.match(/^oklch\(([^)]+)\)/))) { const p = m[1].split(/[ /]+/).filter(Boolean); const L = p[0].endsWith('%') ? parseFloat(p[0]) / 100 : +p[0]; return { rgb: oklchToRgb(L, +p[1], +p[2] || 0), a: p[3] !== undefined ? +p[3] : 1 }; }
    return null;
  }
  const lum = (rgb) => 0.2126 * toLin(rgb[0]) + 0.7152 * toLin(rgb[1]) + 0.0722 * toLin(rgb[2]);
  const blend = (top, bottom) => top.rgb.map((c, i) => c * top.a + bottom[i] * (1 - top.a));
  function background(el) {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const cs = getComputedStyle(e); const p = parse(cs.backgroundColor);
      if (p && p.a > 0) { layers.push(p); if (p.a >= 1) break; }
    }
    let rgb = [1, 1, 1];
    const root = parse(getComputedStyle(document.documentElement).backgroundColor); if (root && root.a >= 1) rgb = root.rgb;
    for (let i = layers.length - 1; i >= 0; i--) rgb = blend(layers[i], rgb);
    return rgb;
  }
  const out = []; const seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const t = walker.currentNode; if (!t.textContent.trim()) continue;
    const el = t.parentElement; if (!el || seen.has(el)) continue; seen.add(el);
    const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    if (r.width === 0 || r.height === 0 || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
    if (el.closest('[disabled],[aria-disabled="true"],[hidden]')) continue;
    const fg = parse(cs.color); if (!fg) { out.push({ text: t.textContent.trim().slice(0, 40), err: cs.color }); continue; }
    const bg = background(el); const fgRgb = blend(fg, bg);
    const a = lum(fgRgb), b = lum(bg); const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    const size = parseFloat(cs.fontSize), bold = +cs.fontWeight >= 700;
    const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    if (ratio < need) out.push({ text: t.textContent.trim().slice(0, 40), ratio: +ratio.toFixed(2), need, cls: (el.className && el.className.baseVal === undefined ? el.className : el.tagName).toString().slice(0, 60), color: cs.color });
  }
  return { theme: document.documentElement.dataset.theme, checked: seen.size, failing: out.length, items: out.slice(0, 40) };
})()
