// IDENTITY BOOKLET TEMPLATE (12 pages, 960 x 1242 px, one HTML file).
// Worked example: a paint-can-lid mark for a painting company. See references/identity-booklet.md.
//
// SWAP THESE FOR A NEW CLIENT
//   1. `dir` and the output paths at the bottom (where the HTML is written).
//   2. Colour constants on the first lines: ACC (accent, used for grounds and crosses), INK, PAINT (brand colour),
//      TIN, PAPER, COBALT (the one allowed exception), SHADE, WOOD, WET. Palettes PAL, MONO, REDONE map them to roles.
//   3. The mark: `jm` (letters), `lidInner` (the mark's shapes), `lid` (sized wrapper with optional paper keyline),
//      and the secondary mark path `DROP`. Keep the viewBox crop in `lid` in step with the mark's real bounds.
//   4. Page text: every string in `pages.push(page(...))`, the voice registers in `reg`, the swatches in `sw`,
//      the variable colours in `cols`, and the footer text inside `page()`.
//   5. Display and text fonts: the 'Bodoni Moda' links in the head string and the Courier fallbacks.
// KEEP: helpers A, lab, page, cross, cmyk, the grain overlay, the zoom scaler and the print CSS.
// Render with a headless browser outside any shell sandbox, view all twelve pages, then export the PDF.
import fs from "node:fs";
const dir = "/private/tmp/claude-501/-Users-jl2/6449a779-d63d-426c-98fe-8418a5fdade2/scratchpad";
let uid = 0;
const ACC = "#f2a38c", INK = "#14110f", PAINT = "#d9251d", TIN = "#c6ccca", PAPER = "#f4f0e6", COBALT = "#1f44b8", SHADE = "#8e9795", WOOD = "#d6a15f", WET = "#9c1712";
const PAL = { ink: INK, tin: TIN, tin2: SHADE, paint: PAINT, dk: WET, let: PAPER, bg: PAPER };
const withPaint = (c) => ({ ...PAL, paint: c });
const MONO = { ink: INK, tin: PAPER, tin2: INK, paint: INK, dk: INK, let: PAPER, bg: PAPER };
const REDONE = { ink: PAINT, tin: PAPER, tin2: PAINT, paint: PAINT, dk: PAINT, let: PAPER, bg: PAPER };

const jm = (cx, cy, h, col) => {
  const id = "c" + ++uid, s = h / 36;
  return `<g transform="translate(${cx} ${cy}) scale(${s})"><clipPath id="${id}"><rect x="-32" y="-18" width="64" height="36"/></clipPath><g clip-path="url(#${id})" fill="none" stroke="${col}" stroke-width="8.6" stroke-linejoin="miter" stroke-miterlimit="10"><path d="M-10.5 -18V6Q-10.5 18-19.5 18Q-28.5 18-28.5 8"/><path d="M-4.5 18V-18L12 6L28.5 -18V18"/></g></g>`;
};
const pol = (r, deg) => [(100 + r * Math.cos((deg * Math.PI) / 180)).toFixed(2), (100 + r * Math.sin((deg * Math.PI) / 180)).toFixed(2)];
const lidInner = (P) => {
  let t = "";
  for (let i = 0; i < 44; i++) { const a = (i / 44) * 360, p = pol(41.5, a), q = pol(45, a); t += `<line x1="${p[0]}" y1="${p[1]}" x2="${q[0]}" y2="${q[1]}"/>`; }
  return `<circle cx="100" cy="100" r="48" fill="${P.ink}"/><circle cx="100" cy="100" r="45.5" fill="${P.tin}"/><g stroke="${P.tin2}" stroke-width="1.7">${t}</g><circle cx="100" cy="100" r="40.5" fill="none" stroke="${P.ink}" stroke-width="1.6"/><circle cx="100" cy="100" r="38.5" fill="${P.tin}"/><circle cx="100" cy="100" r="36" fill="${P.ink}"/><circle cx="100" cy="100" r="34" fill="${P.paint}"/><circle cx="100" cy="51.5" r="3.4" fill="${P.bg}"/><rect x="108" y="124" width="10" height="30" fill="${P.paint}"/><circle cx="113" cy="156" r="7.5" fill="${P.paint}"/>` + jm(100, 100, 32, P.let);
};
const lid = (P, w, { key = false, style = "" } = {}) => `<svg viewBox="48 48 104 120" width="${w}" height="${(w * 120) / 104}" style="${style}" xmlns="http://www.w3.org/2000/svg">${key ? `<circle cx="100" cy="100" r="49.4" fill="none" stroke="${PAPER}" stroke-width="1.1"/>` : ""}${lidInner(P)}</svg>`;

const DROP = "M0 -30C14 -6 22 6 22 16A22 22 0 0 1 -22 16C-22 6 -14 -6 0 -30Z";
const drop = (cx, cy, s, fill) => `<path d="${DROP}" transform="translate(${cx} ${cy}) scale(${s})" fill="${fill}"/>`;

const cross = (c = ACC, s = 18) => `<svg width="${s}" height="${s}" viewBox="0 0 18 18" style="display:block"><path d="M9 0V18M0 9H18" stroke="${c}" stroke-width="1.3"/></svg>`;
const A = (st, html = "", cls = "") => `<div class="a ${cls}" style="${st}">${html}</div>`;
const lab = (st, t, c) => A(st + (c ? `;color:${c}` : ""), t, "lab");
const page = (n, sec, ground, fg, body, { head = true } = {}) => `<div class="page" style="background:${ground};color:${fg}">${head ? lab("left:62px;top:84px", `${String(n).padStart(2, "0")} · ${sec}`) : ""}${body}${head ? lab("left:62px;top:1112px", "JM PAINTING &nbsp;·&nbsp; IDENTITY BOOKLET &nbsp;·&nbsp; FIRST EDITION") + A("left:826px;top:1103px", cross(ACC, 16)) + lab("left:864px;top:1112px", String(n).padStart(2, "0")) : ""}</div>`;

const cmyk = (hex) => { const r = parseInt(hex.slice(1, 3), 16) / 255, g = parseInt(hex.slice(3, 5), 16) / 255, b = parseInt(hex.slice(5, 7), 16) / 255, k = 1 - Math.max(r, g, b); if (k >= 1) return "0 0 0 100"; const f = (x) => Math.round(((1 - x - k) / (1 - k)) * 100); return `${f(r)} ${f(g)} ${f(b)} ${Math.round(k * 100)}`; };

const pages = [];

pages.push(page(1, "", PAPER, INK, lid(PAL, 440, { style: "position:absolute;left:340px;top:130px" }) +
  A("left:310px;top:752px;font-size:21px;line-height:1.25", "JM PAINTING<br>INTERIOR · EXTERIOR · CABINETS<br>OFFICIAL IDENTITY BOOKLET") +
  A("left:310px;top:850px;width:518px;border-top:1px solid " + INK) + A("left:840px;top:840px", cross(ACC, 20)) +
  A("left:310px;top:866px;font-size:21px", "FIRST EDITION") + lab("left:700px;top:1135px", "ANOTHER COAT DONE RIGHT"), { head: false }));

pages.push(page(2, "POSITION", ACC, INK,
  A("left:62px;top:210px;font:italic 500 82px/0.98 'Bodoni Moda','Didot',Georgia,serif;letter-spacing:-.01em;color:" + INK, "Done properly,<br>the first time.") +
  A("left:62px;top:640px;width:486px;font-size:12px;line-height:1.38;text-align:justify", "JM Painting paints homes, cottages and cabinets. The work is measured before it is quoted, prepared before it is painted and finished before we leave. One price, in writing; one crew from the first day to the last. This booklet sets down how that looks and sounds on a van, a sign, an invoice and a phone, so that anyone carrying the mark carries the same standard.") +
  A("left:760px;top:830px", lid(PAL, 110, { key: false })) + lab("left:700px;top:980px;width:171px;text-align:right", "ANOTHER COAT DONE RIGHT") + A("left:850px;top:280px", cross(INK, 18))));

pages.push(page(3, "THE MARK", PAPER, INK,
  A("left:234px;top:96px;width:492px;height:560px;border:1.4px dashed " + ACC) +
  A("left:222px;top:84px", cross(ACC, 24)) + A("left:714px;top:84px", cross(ACC, 24)) + A("left:222px;top:644px", cross(ACC, 24)) + A("left:714px;top:644px", cross(ACC, 24)) +
  lab("left:420px;top:80px;width:310px;text-align:right", "CLEAR SPACE = THE HEIGHT OF THE M", "#d9785c") +
  lid(PAL, 300, { style: "position:absolute;left:330px;top:192px" }) +
  A("left:62px;top:790px;width:520px;font-size:11.5px;line-height:1.4;text-align:justify", "The lid is the JM mark. A paint can lid seen from above: black rim, crimped tin, a disc of red paint with JM in it, and one drip running over the edge. It is always shown as a solid: black and tin on paper, paper on dark ground, one colour when only one is allowed. It is never outlined, never rotated, never given a second drip and never set smaller than 14 mm across.") +
  A("left:620px;top:780px", lid(PAL, 80)) + A("left:720px;top:780px", lid(MONO, 80)) + A("left:812px;top:772px;width:100px;height:112px;background:" + INK, lid(PAL, 80, { key: true, style: "margin:8px 10px" })) +
  lab("left:620px;top:900px", "ON PAPER") + lab("left:720px;top:900px", "ONE COLOUR") + lab("left:812px;top:900px", "ON DARK GROUND")));

const pat = (() => { let s = ""; for (let r = 0; r < 2; r++) for (let i = 0; i < 13; i++) { const x = 62 + i * 64 + (r ? 32 : 0); if (r && i === 12) continue; s += A(`left:${x}px;top:${850 + r * 56}px`, lid(r === 0 && i === 6 ? withPaint(COBALT) : PAL, 60)); } return s; })();
pages.push(page(4, "LOCKUPS", PAPER, INK,
  A("left:62px;top:120px;width:560px;font-size:11.5px;line-height:1.4", "One mark, four ways to carry it. The lid never changes; the words move around it. Word lockups are set in Courier, caps, and sit on the lid's baseline or its left edge, never centred beneath it.") +
  A("left:62px;top:226px", lid(PAL, 100)) + A("left:182px;top:250px;font-size:27px", "JM PAINTING") + A("left:182px;top:288px;font-size:11px", "INTERIOR · EXTERIOR · CABINETS") + lab("left:62px;top:356px", "A · HORIZONTAL") +
  A("left:590px;top:210px", lid(PAL, 120)) + A("left:590px;top:358px;font-size:28px", "JM") + A("left:590px;top:394px;font-size:13px;letter-spacing:.25em", "PAINTING") + lab("left:590px;top:440px", "B · STACKED") +
  A("left:62px;top:540px;width:400px;height:150px;background:" + INK + ";transform:rotate(-7deg);color:" + PAPER, lid(PAL, 96, { key: true, style: "position:absolute;left:36px;top:16px" }) + A("left:170px;top:48px;font-size:17px", "JM PAINTING") + A("left:170px;top:76px;font-size:10px;letter-spacing:.08em", "FREE ESTIMATES<br>jmpainting.co") + A("left:376px;top:70px;width:10px;height:10px;border-radius:50%;background:" + PAPER)) + lab("left:62px;top:742px", "C · THE SIGN") +
  A("left:540px;top:540px;width:330px;height:190px;border:1px solid " + INK, lid(PAL, 62, { style: "position:absolute;left:18px;top:14px" }) + A("left:18px;top:128px;font-size:12px", "ALEX MORGAN") + A("left:18px;top:146px;font-size:8.5px", "OWNER") + A("right:16px;top:128px;text-align:right;font-size:8.5px;line-height:1.5", "JM PAINTING<br>Interior · Exterior · Cabinets<br>jmpainting.co") + A("right:16px;top:14px", cross(ACC, 16))) + lab("left:540px;top:752px", "D · THE CARD") +
  pat + lab("left:62px;top:990px", "E · THE PATTERN. LIDS TILE LIKE TUMBLING BLOCKS, ALL PAINT RED, ONE IN COBALT. USE AS A BORDER OR END-PAPER, NEVER BEHIND TEXT.")));

pages.push(page(5, "THE DROP", INK, PAPER,
  `<svg class="a" style="left:62px;top:180px" width="260" height="300" viewBox="-40 -40 80 90">${drop(0, 0, 1.05, PAINT)}</svg>` +
  `<svg class="a" style="left:560px;top:150px" width="330" height="330" viewBox="-60 -60 120 120"><circle r="58" fill="${PAPER}"/>${drop(0, -2, 1.5, PAINT)}</svg>` +
  `<svg class="a" style="left:225px;top:600px" width="290" height="290" viewBox="-60 -60 120 120"><circle r="58" fill="${PAINT}"/>${drop(0, -2, 1.5, PAPER)}${drop(0, 8, 0.7, PAINT)}</svg>` +
  lab("left:150px;top:500px", "DROP") + lab("left:716px;top:500px", "DISC") + lab("left:360px;top:906px", "DOUBLED") +
  A("left:570px;top:690px;width:300px;font-size:11.5px;line-height:1.4;text-align:justify", "The secondary mark. One drop, three cuts: the open drop, the drop in a disc, the doubled drop. It stands for the finish: wet, clean, done. It is never paired with the lid on the same face. One mark speaks at a time. It lives on ink, and appears on stickers, tape, job sheets and the back of the invoice.") +
  lab("left:640px;top:1000px;width:231px;text-align:right", "RED ON INK · NEVER ON RED")));

const sw = [["INK", INK], ["PAINT", PAINT], ["TIN", TIN], ["PAPER", PAPER], ["COBALT", COBALT], ["PEACH", ACC], ["STEEL", SHADE], ["WOOD", WOOD]];
const swh = sw.map(([n, h], i) => { const x = 62 + (i % 4) * 207, y = i < 4 ? 250 : 640; return A(`left:${x}px;top:${y}px;width:190px;height:290px;background:${h};${h === PAPER ? "border:1px solid " + INK : ""}`) + A(`left:${x}px;top:${y + 304}px;font-size:10px`, n) + lab(`left:${x}px;top:${y + 322}px;font-size:9px`, h.toUpperCase()) + lab(`left:${x}px;top:${y + 338}px`, "CMYK " + cmyk(h)); }).join("");
pages.push(page(6, "COLOUR", PAPER, INK, A("left:62px;top:120px;width:560px;font-size:11.5px;line-height:1.4", "One red carries the brand; the rest are the colours of the tin and the tools. Paint red is for the paint, the drip and the rule: never a background. Tin is the metal of the lid. Peach is the accent: grounds, crosses and guides, never inside the mark. Cobalt is the one colour allowed to replace the red, in a client's job or a single exception.") + swh));

pages.push(page(7, "TYPE", PAPER, INK,
  A("left:56px;top:150px;font:italic 500 190px/1 'Bodoni Moda','Didot',Georgia,serif;letter-spacing:-.02em", "Paint") +
  A("left:62px;top:390px;font:italic 500 30px 'Bodoni Moda','Didot',Georgia,serif", "Bodoni Moda Italic") +
  A("left:62px;top:440px;font:italic 500 19px 'Bodoni Moda','Didot',Georgia,serif;white-space:nowrap", "ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz 0123456789 &") +
  A("left:62px;top:490px;width:420px;font-size:10px;line-height:1.5", "The display face. It is the voice of the sign painter: a high-contrast italic with hairline serifs. One line per surface at most, never below 28 pt, never in caps, never letterspaced. For lettering at scale the vector lid is used, not this face.") +
  A("left:62px;top:680px;font-size:64px", "Courier") + A("left:62px;top:760px;font-size:15px", "THE TEXT FACE &nbsp;·&nbsp; CAPS FOR LABELS, MIXED FOR RUNNING TEXT") +
  A("left:62px;top:800px;font-size:11px;white-space:nowrap", "ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz 0123456789 +-=/()[]{}<>@#$%&*") +
  A("left:62px;top:836px;width:520px;font-size:11px;line-height:1.4;text-align:justify", "Everything else is Courier. Estimates, invoices, job sheets, captions and this paragraph. It reads like a carbon copy because it is one: fixed width, unretouched, the same on a printer and on a phone. Set it 9 to 12 pt for text, 6 to 8 pt for labels, 21 pt only on the cover block. Leading is 1.4 for text. Justify running text; never justify labels.") +
  A("left:700px;top:690px;width:171px;text-align:right;font-size:8px", "JM LABEL") + A("left:700px;top:732px;width:171px;text-align:right;font-size:11px", "JM TEXT") + A("left:700px;top:772px;width:171px;text-align:right;font-size:14px", "JM LEAD") + A("left:620px;top:810px;width:251px;text-align:right;font-size:21px", "JM COVER")));

const reg = [["ESTIMATE", "What, how many coats, how many days, the price. In that order.", "Two coats, walls and ceilings, four rooms, three days. $4,860 plus HST. Valid 30 days.", "We would love to transform your space with a stunning fresh new look!"],
  ["INVOICE", "What was done, what was paid, what is owed, when.", "Deposit paid: $2,430. Balance $2,430 due on completion.", "Please kindly remit payment at your earliest convenience."],
  ["REVIEW REPLY", "Thank them by name. Say what happens next.", "Thank you, Priya. The hallway touch-up is booked for Friday morning.", "We value your feedback and strive for excellence in all we do."],
  ["SITE NOTE", "Room, what was done, what is next, when.", "Master bedroom: patched, sanded, primed. Second coat tomorrow, 9 a.m.", "Work in progress, all going well!"]];
const regh = reg.map(([n, d, y, no], i) => { const t = 330 + i * 195; return A(`left:62px;top:${t}px;font-size:11px`, n) + A(`left:208px;top:${t}px;font-size:10px`, d) + A(`left:62px;top:${t + 30}px;width:809px;border-top:1px solid ${INK}`) + lab(`left:62px;top:${t + 56}px`, "YES") + A(`left:208px;top:${t + 52}px;font-size:11px`, y) + lab(`left:62px;top:${t + 98}px`, "NO", PAINT) + A(`left:208px;top:${t + 94}px;font-size:11px;color:${PAINT}`, no); }).join("");
pages.push(page(8, "VOICE", TIN, INK, A("left:60px;top:136px;font:italic 500 68px/1 'Bodoni Moda','Didot',Georgia,serif", "Say what we will paint,<br>and when.") + A("left:62px;top:268px;width:560px;font-size:11.5px;line-height:1.4", "JM writes the way it paints: every line covers one thing, and nothing is done twice. The four registers below cover almost everything the company sends. If a piece of writing does not fit one, it is probably not finished.") + regh));

const rect = (c, extra = "") => `background:${c};${extra}`;
const stampSvg = `<svg width="240" height="240" viewBox="-120 -120 240 240" style="transform:rotate(-7deg)"><circle r="112" fill="none" stroke="${PAINT}" stroke-width="2.4"/><circle r="104" fill="none" stroke="${PAINT}" stroke-width="1"/><defs><path id="sp" d="M-80 0A80 80 0 1 1 80 0A80 80 0 1 1 -80 0"/></defs><text font-family="Courier New,monospace" font-size="12.5" letter-spacing="2.6" fill="${PAINT}"><textPath href="#sp">JM PAINTING · INTERIOR · EXTERIOR · CABINETS · FREE ESTIMATES ·</textPath></text><g transform="translate(-52 -60) scale(.52)">${lid(REDONE, 200).replace('<svg ', '<svg x="0" y="0" ')}</g></svg>`;
pages.push(page(9, "SURFACES", PAPER, INK,
  A("left:62px;top:120px;width:560px;font-size:11.5px;line-height:1.4", "The mark on the small screens it will spend most of its life on. The app icon is the lid on ink with a paper keyline; the favicon is the same lid at 32 px; the avatar is the drop on paint red. Nothing else goes in a rounded square.") +
  A("left:62px;top:250px;width:214px;height:214px;border-radius:50px;background:" + INK, lid(PAL, 150, { key: true, style: "margin:32px 32px" })) +
  A("left:354px;top:380px", `<div style="width:62px;height:62px;border-radius:15px;background:${INK}">${lid(PAL, 44, { key: true, style: "margin:8px 9px" })}</div>`) +
  A("left:451px;top:410px", `<div style="width:32px;height:32px;border-radius:8px;background:${INK}">${lid(PAL, 24, { key: true, style: "margin:4px 4px" })}</div>`) +
  A("left:548px;top:426px", `<div style="width:16px;height:16px;border-radius:4px;background:${INK}">${lid(PAL, 12, { key: true, style: "margin:2px 2px" })}</div>`) +
  lab("left:62px;top:480px", "APP ICON · 1024") + lab("left:354px;top:480px", "FAVICON · 64 · 32 · 16") +
  A("left:62px;top:530px;width:214px;height:214px;border-radius:50%;background:" + PAINT, `<svg width="214" height="214" viewBox="-60 -60 120 120">${drop(0, -2, 1.5, PAPER)}</svg>`) +
  A("left:354px;top:530px;width:214px;height:214px;border-radius:50px;background:" + PAPER + ";border:1.5px solid " + INK, `<svg width="214" height="214" viewBox="-60 -60 120 120"><circle r="46" fill="${INK}"/>${drop(0, 0, 1.0, PAPER)}</svg>`) +
  A("left:630px;top:512px", stampSvg) +
  lab("left:62px;top:760px", "AVATAR · THE DROP ON PAINT") + lab("left:354px;top:760px", "DROP · 1024") + lab("left:600px;top:760px;width:271px;text-align:right", "THE STAMP · RED, HAND-STRUCK, ALWAYS CROOKED")));

const vanSvg = (w) => `<svg viewBox="0 0 420 190" width="${w}"><path d="M12 140V74Q12 50 36 50H250Q276 50 294 78L336 100Q394 106 402 128V140Z" fill="${PAPER}" stroke="${INK}" stroke-width="3"/><path d="M268 60H288Q302 78 322 98H268Z" fill="#9fb2bd"/><rect x="12" y="128" width="390" height="12" fill="${INK}"/><rect x="12" y="122" width="390" height="5" fill="${PAINT}"/><circle cx="90" cy="142" r="20" fill="${INK}"/><circle cx="90" cy="142" r="9" fill="${TIN}"/><circle cx="324" cy="142" r="20" fill="${INK}"/><circle cx="324" cy="142" r="9" fill="${TIN}"/><svg x="34" y="58" width="62" height="71" viewBox="48 48 104 120">${lidInner(PAL)}</svg><text x="112" y="88" font-family="Courier New,monospace" font-size="19" font-weight="700" fill="${INK}" letter-spacing="2">JM PAINTING</text><text x="112" y="106" font-family="Courier New,monospace" font-size="9.5" fill="${INK}" letter-spacing="1">INTERIOR · EXTERIOR · CABINETS</text></svg>`;
pages.push(page(10, "IN USE", PAPER, INK,
  A("left:62px;top:120px;width:560px;font-size:11.5px;line-height:1.4", "Four places the mark has to work without help: the side of a van, a sign on a lawn, a card in a hand, an invoice on a kitchen table. In each the lid sits alone, with room round it, and the words are Courier.") +
  A("left:62px;top:240px;width:809px;height:330px;background:#dfe0da", A("left:100px;top:56px", vanSvg(610))) + lab("left:62px;top:584px", "THE VAN") +
  A("left:62px;top:640px;width:390px;height:420px;background:#dfe0da", A("left:70px;top:40px;width:250px;height:220px;background:" + INK + ";box-shadow:6px 6px 0 " + SHADE + ";text-align:center;color:" + PAPER, lid(PAL, 130, { key: true, style: "margin-top:18px" }) + A("left:0;right:0;top:162px;font-size:15px;letter-spacing:.14em", "JM PAINTING") + A("left:0;right:0;top:188px;font-size:9px;opacity:.7", "FREE ESTIMATES · jmpainting.co")) + A("left:186px;top:260px;width:18px;height:90px;background:#8a6a40") + A("left:70px;top:260px;width:18px;height:90px;background:#8a6a40;opacity:0") + A("left:300px;top:260px;width:18px;height:90px;background:#8a6a40;opacity:0")) + lab("left:62px;top:1070px;top:1068px", "THE SIGN") +
  A("left:481px;top:640px;width:390px;height:420px;background:#dfe0da", A("left:34px;top:46px;width:322px;height:328px;background:" + PAPER + ";box-shadow:4px 4px 0 " + INK, lid(PAL, 74, { style: "position:absolute;left:24px;top:20px" }) + A("left:218px;top:30px;font-size:15px;letter-spacing:.1em;width:90px;text-align:right", "INVOICE") + A("left:24px;top:162px;width:274px;border-top:3px solid " + PAINT) + A("left:24px;top:180px;font-size:10px;line-height:1.7;width:274px", "Interior, 4 rooms ........ $4,860<br>HST ............................ $632<br>Deposit paid ........... −$2,430") + A("left:24px;top:276px;font-size:13px;font-weight:700", "DUE ON COMPLETION &nbsp; $3,062"))) + lab("left:481px;top:1068px", "THE INVOICE")));

const cols = [[PAINT, "PAINT RED"], [COBALT, "COBALT"], ["#f2b705", "YELLOW"], ["#1f7a4d", "GREEN"], ["#ec4d84", "PINK"], [INK, "BLACK"]];
pages.push(page(11, "THE PAINT", "#e7e3d6", INK,
  A("left:60px;top:140px;font:italic 500 70px/1 'Bodoni Moda','Didot',Georgia,serif", "The ring stays.<br>The paint changes.") +
  A("left:62px;top:320px;width:540px;font-size:11.5px;line-height:1.4;text-align:justify", "Only the disc of paint takes the client's colour. The tin, the rim, the crimp and the drip stay as drawn. A lid in the colour of the job goes on the job sheet, the thank-you card and the finished-room photo. The house mark is always red.") +
  cols.map(([c, n], i) => A(`left:${62 + (i % 3) * 280}px;top:${470 + Math.floor(i / 3) * 300}px`, lid(withPaint(c), 190)) + lab(`left:${62 + (i % 3) * 280}px;top:${470 + Math.floor(i / 3) * 300 + 232}px`, n + " " + c.toUpperCase())).join("")));

pages.push(page(12, "", INK, PAPER, lid(PAL, 440, { key: true, style: "position:absolute;left:340px;top:130px" }) +
  A("left:310px;top:752px;font-size:21px;line-height:1.25", "JM PAINTING<br>INTERIOR · EXTERIOR · CABINETS<br>jmpainting.co") + A("left:310px;top:850px;width:518px;border-top:1px solid " + PAPER) + A("left:840px;top:840px", cross(ACC, 20)) +
  A("left:310px;top:866px;font-size:21px", "FIRST EDITION · NOVEMBER 2026") + lab("left:310px;top:1135px", "jmpainting.co") + lab("left:700px;top:1135px", "ANOTHER COAT DONE RIGHT"), { head: false }));

const grain = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='240' height='240'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 .10 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>";
const html = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>JM Painting Identity Booklet</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bodoni+Moda:ital,opsz,wght@1,6..96,500&display=swap">
<style>*{box-sizing:border-box}body{margin:0;background:#2a2724;padding:24px 0}.set{width:960px;margin:0 auto;transform-origin:top left}
.page{position:relative;width:960px;height:1242px;overflow:hidden;margin:0 0 24px;font-family:'Courier New',Courier,monospace;color:${INK}}
.page::after{content:"";position:absolute;inset:0;pointer-events:none;mix-blend-mode:multiply;background-image:url("${grain}")}
.a{position:absolute}.lab{font-size:8.5px;letter-spacing:.1em;text-transform:uppercase;white-space:nowrap}svg{display:block}
@media print{body{background:none;padding:0}.page{margin:0;page-break-after:always}}</style></head><body><div class="set" id="set">${pages.join("")}</div>
<script>function fit(){var s=Math.min(1,(innerWidth-16)/960),e=document.getElementById('set');e.style.zoom=s}fit();addEventListener('resize',fit)</script></body></html>`;
fs.writeFileSync(`${dir}/jm-identity-booklet.html`, html);
fs.copyFileSync(`${dir}/jm-identity-booklet.html`, "/Users/jl2/Desktop/jm-identity-booklet.html");
console.log("ok", pages.length);
