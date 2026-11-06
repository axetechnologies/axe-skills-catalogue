# The identity booklet

A 12-page portrait booklet that turns a chosen mark into a system: what it is, how it is carried, what colours, type and words go with it, and where it lives. The format below was read from a reference brand booklet (page images viewed one by one) and then built and checked for a real client. Treat it as a format, not as someone else's brand: swap every mark, colour and sentence.

## Why this format
A logo sheet shows ideas. A booklet shows judgement: the rules (never outlined, never rotated, never smaller than X) are what make a mark look owned. One idea per page, mostly empty, with the application doing the persuading, as in the archive's presentation books (`what-the-work-shows.md`).

## Page and surface
- Page 960 x 1242 px (portrait, close to US letter). Absolute positioning inside each page, so layout is exact. Scale the set to the window with `zoom: min(1, (innerWidth - 16) / 960)`.
- Grain: an inline SVG `feTurbulence` noise as a `::after` overlay, `mix-blend-mode: multiply`, about 10% alpha. It makes flat colour feel like stock.
- Registration crosses: a thin `+` in the accent colour at the end of the cover rule, in the footer beside the page number, and at the four corners of the clear-space box.
- Header: `NN · SECTION` in 8.5px tracked caps at top-left (left 62, top 84). Footer: `BRAND · IDENTITY BOOKLET · FIRST EDITION` left, a cross and the page number right (top 1112). The cover and the closing page have no header or footer.
- Type: one monospace (Courier) for everything including body, justified for running text and never for labels; one high-contrast display italic (Didone) for one line per page at 60 to 190 px. Nothing else.
- Each page has its own full-bleed ground: paper, accent, ink, a grey, a pale tint. The colour change is the page turn.

## The twelve pages and their jobs
1. **Cover.** The mark large on paper, set right of centre. Left-aligned Courier title block (name, discipline, "official identity booklet"), a hairline rule ending in a cross, "FIRST EDITION". A tiny line bottom right.
2. **Position.** Accent ground. One display-italic sentence, one justified paragraph of what the company does and why this booklet exists, the mark small bottom right with its line.
3. **The mark.** The mark large inside a dashed clear-space box with crosses at the corners and a label saying what the clear space equals (a part of the mark itself, such as the height of a letter). A paragraph of rules, and three small versions: on paper, one colour, on dark ground.
4. **Lockups.** Horizontal, stacked, a sign or tag (rotated, on ink), a business card, and a pattern strip of the mark tiled like tumbling blocks with one element in a different colour. Words sit on the mark's baseline or left edge, never centred under it.
5. **Secondary mark.** On ink. A single simple shape taken from the primary mark in three cuts (open, in a disc, doubled). Rules for where it lives and that it never shares a face with the primary.
6. **Colour.** Eight tall swatches in two rows of four, each with name, hex and CMYK. Say which one colour is the brand, which is never a background, and which is the accent.
7. **Type.** The display face at huge size with its alphabet, then the text face with its alphabet, then the four sizes (label, text, lead, cover). Give point sizes, leading, and the "never" rules.
8. **Voice.** Four registers (for example estimate, invoice, review reply, site note). For each: the rule, one YES line, one NO line in the accent-red. Real numbers and names, never lorem.
9. **Surfaces.** App icon (mark on ink with a paper keyline), favicon at 64/32/16, avatar (secondary mark), a rounded-square variant of the secondary mark, and a stamp: a ring with text on a path around the mark, one colour, rotated a few degrees.
10. **In use.** Vehicle, sign, card, invoice or the equivalents for the trade. The mark sits alone with room round it; the words are the text face.
11. **The system's variable.** The page that shows what may change (for example the one colour that takes the client's job) and what never does. Six small versions.
12. **Closing.** Reverse of the cover on ink, with the mark carrying a paper keyline so a dark rim stays visible.

## Dark-ground rule
A mark with a dark outer rim disappears on ink. Add a 1.1px paper keyline circle just outside the rim (and a rounded-square tile for icons). Never solve it by recolouring the rim.

## Build recipe
1. Start from `assets/identity-booklet-template.mjs`. Swap the colour constants, the mark functions (`lidInner`, `lid`), the secondary-mark path, and the text of each page. Keep the helpers `A` (absolute box), `lab` (label), `page` (ground, header, footer), `cross`, `cmyk`.
2. `node` it to write the HTML, then render every page to a PNG with a headless browser and look at all twelve on a contact sheet, then at the pages you changed at full size.
3. Export a PDF with the same browser (`page.pdf` at 960 x 1242 px, `printBackground: true`, print media).
4. Check 390px width for horizontal scroll (the `zoom` scaler handles it).

## Pitfalls hit while building
- `A()` called with styles only printed the word `undefined` on screen. Default the html argument to `""`.
- Long concatenated template calls lose a closing parenthesis easily; a missing one fails the whole script with `missing ) after argument list`. Close each nested `A(...)` on its own, or build children into variables first.
- A headless browser will not launch inside a restrictive shell sandbox (Chrome fails on crashpad or sandbox-extension errors). Run the render step outside the sandbox.
- A shell `sed -i` with no backup suffix fails on macOS; use `sed -i ''` or edit with Python.
- Peach or other pale accents are faint as hairline crosses on paper. Use them for grounds and large crosses; give any accent text a darker shade.
- Fonts come from a web font link; offline renders fall back to Didot or Georgia. Wait for network idle before screenshots.
- Never call a page good from the code. Render and look.
