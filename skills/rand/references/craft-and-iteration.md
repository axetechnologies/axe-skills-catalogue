# Craft and iteration

How to get from "a set of ideas" to work that is actually good, and how to respond when told it is not there yet.

## 1. The loop: make, look, critique, revise
Never judge your own design from the code. Render it and look at it.

1. **Make** the smallest version that expresses the idea.
2. **Render** it (headless browser screenshot, at desktop and at 390px wide). Look at the image, not the source.
3. **Critique** against the rubric below. Write down the three worst problems, in plain words.
4. **Revise** only those three. Do not touch what works.
5. **Repeat** at least twice before showing anything. Show the second or third render, not the first.

If a screenshot reveals something the code did not predict (clipping, a broken one-colour version, a mark that looks like something else), that is the loop working. Fix it before presenting.

## 2. Rubric (score each 0-10, total 100)
| Dimension | Question |
|---|---|
| Idea | Can it be said in one sentence? Is it true of this subject, and not of any competitor? |
| Name | Does the mark contain the initials or name, or does it need a caption to belong to this client? |
| Geometry | One stroke weight, one corner rule, one angle family. Optical corrections made by eye. |
| Type | Designed, not defaulted. A deliberate pairing, tracked and sized for its job. |
| Material and depth | If depth is used, it follows one light, has three values per form, and carries meaning. If flat, the flat is crisp. |
| Memorability | After five seconds away, can you draw it from memory? |
| Versatility | Works in one colour, reversed, at 16px, blurred, on a van, a card, an invoice, an app icon. |
| System | There is a specification: colours, type, construction, minimum size, usage. |
| Restraint | Nothing present that could be removed without loss. The accent is used once or twice, not everywhere. |
| Mobile and delivery | Presented at 390px without horizontal scroll, assets delivered as real files. |

Under 60 is not ready to show. 60 to 79 needs another loop. 80 and above is a candidate.

## 3. When the feedback is a number or a feeling
"30 percent there", "zero depth", "not premium": treat it as a score on a dimension, not a verdict on taste.
1. Name what is likely missing in the rubric terms above. The common causes, in order: no initials in the mark, a default font, effects instead of an idea, no system, no craft in the lettering.
2. Say plainly what was weak in the last round before showing the next. A short honest critique builds trust and focuses the work.
3. Change the approach, not the decoration. Fewer concepts, developed further, beat more concepts at the same depth.
4. Show the system the mark lives in, because "it looks like an icon, not a brand" is usually a system problem.

## 4. Lettering and mark construction
- **Start from a strong typeface and modify it** (a cut, an offset, a clip, a join) before drawing letters from scratch. The modification is the idea: a diagonal cut, a tape edge, a drip from a foot, panes inside a window.
- **Monoline systems:** pick one stroke width (for example 12 units on a 100-unit height), round or mitred joins everywhere, angles from a short list (90, 45, 30). Draw every letter from the same list.
- **Optical corrections:** round shapes overshoot flat ones by 2-3 percent. Thin joins need slightly thicker strokes than the maths says. Check the mark upside down: gaps and weights that look wrong are wrong.
- **Spacing:** space letters by the area between them, not the distance. Kern the pair that looks loosest first.
- **Always draw a flat version.** One colour, no effects. If the idea only works with the shading, the idea is not done.
- **The accent appears once or twice**, in a place that carries meaning (the tip of the brush, the falling drop, the tape).

## 5. Rendering material (when depth is wanted)
- **Extrusion** for solid forms: draw seven or eight copies offset by about 1 unit down and right in a darker value, then the front face. It reads as cut metal or stone, and avoids the blurred-shadow look.
- **Thick paint:** a darker offset underneath, the face with a light-to-dark gradient, a thin white highlight along the top-left edge, a darker lower edge.
- **Wet or glossy:** a rounded specular highlight (an ellipse at 50 to 60 percent white), placed on the lit side, plus a small second highlight.
- **Metal:** a four-stop horizontal gradient: shadow, light, mid, dark.
- **Glass:** a 45 degree triangle at 25 to 30 percent white in one corner, a darker inner reveal.
- **Ground:** a soft ellipse shadow beneath, 20 to 25 percent black, the width of the object.
- **Colour:** build the light and dark values from the base with `color-mix` toward white and toward black so one variable recolours the whole object. Keep the light value saturated (mix about 70 percent base with 30 percent white), or it looks washed out.

## 6. Identity system deliverables
A mark is not an identity until it shows up in use. For each flagship concept show:
- The mark with a designed wordmark and a one-sentence idea.
- A specification: palette with names and hex values, type, five or six construction notes, and what the flat version is.
- Variants: horizontal and stacked lockups, one colour, reversed, app icon, 64/32/16px, a blur test.
- Context mockups: a vehicle, a yard sign, a business card, an invoice header. Use plain HTML and CSS so they scale.
- A closing recommendation with the reasoning, and the next step (which concept to finish, which files will follow).

## 7. Mobile and responsive checks
- Every page of the work is checked at 360px and 390px. No horizontal scroll, tap targets 44px or more, type readable without zoom.
- Fixed pixel widths on logos and images become `max-width: 100%` with a width capped by `min()`. Grid children that hold text or images need `min-width: 0`.
- Depth on phones is lighter: smaller blur radius, fewer stacked shadows, parallax off on touch and under reduced motion.
- Sticky headers, floating cards and bottom bars must not cover content, anchors or the on-screen keyboard. Give anchored sections a scroll offset equal to the header height.
- Test by measuring (scrollWidth minus clientWidth, bounding boxes of anything wider than the viewport), then look at the screenshot.

## 8. Presenting
- Lead with the recommendation and the reason.
- Say what was wrong with the last round in two or three lines.
- Show less. Five developed identities beat twenty icons.
- Offer the next step, not a menu.
