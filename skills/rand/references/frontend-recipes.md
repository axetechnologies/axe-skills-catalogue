# Front-end recipes

Copy, then adapt. All snippets are framework neutral.

## 1. Tokens first
```css
:root {
  /* colour: 4-6 named tokens, each with a job */
  --paper: #fbfbf8;  --ink: #1b211d;  --signal: #c9462f;  --support: #2b4c9b;  --line: #dcdfd8;
  /* type: two roles */
  --font-display: "Archivo Black", "Arial Black", system-ui, sans-serif;
  --font-text: "Archivo", system-ui, -apple-system, "Segoe UI", sans-serif;
  /* scale: large steps */
  --step-0: 1rem; --step-1: 1.5rem; --step-2: 2.5rem; --step-3: 4.5rem;
  /* space: one rhythm */
  --s-1: .25rem; --s-2: .5rem; --s-3: 1rem; --s-4: 2rem; --s-5: 4rem; --s-6: 8rem;
  /* motion */
  --ease: cubic-bezier(.22,.61,.36,1); --dur: 240ms; --dur-slow: 480ms;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --paper:#121613; --ink:#eef0ea; --line:#2b322d; color-scheme: dark; } }
:root[data-theme="dark"] { --paper:#121613; --ink:#eef0ea; --line:#2b322d; color-scheme: dark; }
body { background: var(--paper); color: var(--ink); font-family: var(--font-text); }
```
Rule: no raw colour, size or duration appears in a component. If you need a new one, add a token and name its job.

## 2. Asymmetric layout
```css
.page { display: grid; grid-template-columns: minmax(0, 7fr) minmax(0, 3fr); gap: var(--s-5); align-items: end; }
.page > .lead { grid-column: 1; }   /* big statement */
.page > .aside { grid-column: 2; }  /* small, quiet, offset */
@media (max-width: 760px) { .page { grid-template-columns: 1fr; gap: var(--s-4); } }
```
Heavy against light, wide against narrow, filled against empty. Align to two or three shared edges.

## 3. Hierarchy with contrast
```css
h1 { font: 400 clamp(2.5rem, 7vw, 5.5rem)/.95 var(--font-display); letter-spacing: -.02em; text-wrap: balance; }
.label { font: 600 .75rem/1 var(--font-text); letter-spacing: .16em; text-transform: uppercase; }
```
Large steps only. Two weights, one display size, one text size, one label size.

## 4. Marks from primitives (SVG)
- Draw on a 100x100 grid. Use `fill="currentColor"` for the main shape and a variable for the accent so the mark recolours.
```html
<svg viewBox="0 0 100 100" role="img" aria-label="Mark">
  <circle cx="50" cy="50" r="40" fill="var(--ink)"/>
  <rect x="46" y="12" width="8" height="52" rx="4" fill="var(--signal)"/>
</svg>
```
- Letters from geometry: stems are rectangles, bowls are arcs (`A r r 0 0 1 x y`), joins are straight cuts. Hand-fix optical errors: round shapes overshoot flat ones by about 2-3%.
- Stripe or bar treatment (repetition): mask a bold shape with evenly spaced bars.
```html
<mask id="cut"><rect width="100" height="100" fill="#000"/><text x="50" y="74" text-anchor="middle" font-size="70" fill="#fff">JM</text>
  <rect y="24" width="100" height="3.5"/><rect y="37" width="100" height="3.5"/><rect y="50" width="100" height="3.5"/></mask>
<rect width="100" height="100" fill="currentColor" mask="url(#cut)"/>
```
(set the cut rectangles to `fill="#000"`.)
- A rebus: pick the object, pick the letter that shares its silhouette, join them at the shared edge. If you have to explain it, redraw.

## 5. Components
- One primary action per view; its label is a verb phrase that says the outcome.
- Errors: say what happened and what to do. Empty states: say what will appear and how to add the first item.
- Focus ring: `outline: 3px solid var(--signal); outline-offset: 2px;` Never remove focus styles without replacing them.
- Tap targets 44px or more. Forms: a visible label for every field.

## 6. Motion kit (purposeful, short, once)
```css
.reveal { animation: rise var(--dur-slow) var(--ease) both; }
@keyframes rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
.stagger > * { animation: rise var(--dur-slow) var(--ease) both; animation-delay: calc(var(--i, 0) * 55ms); }
.paint-on { transform-box: fill-box; transform-origin: 0 50%; animation: wipe 700ms var(--ease) both; }
@keyframes wipe { from { transform: scaleX(0); } to { transform: scaleX(1); } }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: 1ms !important; transition-duration: 1ms !important; } }
```
Use motion to show order (stagger in reading order), cause (the thing you clicked responds), or result (count-up to a number). Not for ambience.

## 7. Logo test harness
Drop in a page to run the standard tests at a glance.
```html
<div class="tests">
  <figure><svg class="t t-normal">…</svg><figcaption>Normal</figcaption></figure>
  <figure><svg class="t t-mono">…</svg><figcaption>One colour</figcaption></figure>
  <figure class="dark"><svg class="t t-reverse">…</svg><figcaption>Reversed</figcaption></figure>
  <figure><svg class="t t-blur">…</svg><figcaption>Blur</figcaption></figure>
  <figure><svg class="t t-16">…</svg><figcaption>16px</figcaption></figure>
</div>
<style>
.t-mono { filter: grayscale(1) contrast(1000%); }       /* forces black and white */
.t-blur { filter: blur(3px); }
.t-16 { width: 16px; height: 16px; }
.dark { background: #1b211d; } .t-reverse { filter: invert(1) grayscale(1); }
</style>
```
If the blurred version stops reading as the right shape, the idea is in the detail, not the form.

## 8. Dark mode and contrast
Build both themes from the same tokens. Check body text at 4.5:1 and large text and UI parts at 3:1. Accent colours often need a lighter value on dark grounds. Never rely on colour alone for state.

## 9. Delivery checklist
Tokens file, mark as SVG (colour, mono, reversed), favicon set, one specimen sheet, usage notes (clear space, minimum size), and one page of rationale.

## 10. Depth kit
```css
:root {
  --shadow-1: 0 1px 2px rgb(0 0 0 / .10), 0 2px 6px rgb(0 0 0 / .08);       /* resting */
  --shadow-2: 0 4px 10px rgb(0 0 0 / .12), 0 10px 24px rgb(0 0 0 / .10);     /* raised */
  --shadow-3: 0 12px 24px rgb(0 0 0 / .16), 0 28px 60px rgb(0 0 0 / .14);    /* floating */
  --sheen: linear-gradient(180deg, rgb(255 255 255 / .35), rgb(255 255 255 / 0) 45%);
  --edge-light: inset 0 1px 0 rgb(255 255 255 / .45);                       /* top-left light catches the edge */
  --edge-dark: inset 0 -2px 0 rgb(0 0 0 / .18);
}
.card { box-shadow: var(--shadow-1), var(--edge-light); transition: transform var(--dur) var(--ease), box-shadow var(--dur) var(--ease); }
.card:hover { transform: translateY(-3px); box-shadow: var(--shadow-2), var(--edge-light); }
.card:active { transform: translateY(0); box-shadow: var(--shadow-1); }
.btn-primary { background: var(--signal); box-shadow: var(--shadow-1), var(--edge-light), var(--edge-dark); }
@media (prefers-reduced-motion: reduce) { .card:hover { transform: none; } }
```
SVG object: a linear gradient from a light, through the base, to a dark colour built with `color-mix(in srgb, var(--accent) 60%, #fff)` and `color-mix(in srgb, var(--accent) 68%, #000)`, plus `<feDropShadow dx="0" dy="3" stdDeviation="2.4" flood-opacity=".3"/>`.
Layered page: use parallax sparingly (a slow translate on one background plane), z-index tokens, and a clear stacking order: page, section surfaces, cards, sticky header, overlays.
