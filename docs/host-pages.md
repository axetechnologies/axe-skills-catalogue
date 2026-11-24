# Host pages: one hub, three pages

The hub answers on several hostnames. Three of them get a page of their own at `/`; every other host gets the browsable index it always got.

| Host | Page | Brand |
|---|---|---|
| `skills.axe.onl` | AXe skills hub: the promotion line over skills, plugins and connectors | AXe |
| `barracks.0perator.co` | Barracks, the Operator skills marketplace | Operator (the live 0perator.co brand) |
| `operator.axetechnologies.ca` | Operator as an AXe product, with a live marketplace section | AXe parent, Operator product |

## Routing

- The page is chosen by the `Host` header, matched case-insensitively and without the port.
- `X-Forwarded-Host` is believed only when the request comes from a loopback address, as the tunnel's does. From anywhere else it is ignored, so a caller cannot name a host it is not on.
- Only `/` and `/assets/*` are host-aware. `/v1/*`, `/openapi.json`, `/healthz`, `/docs/*`, `/portal` and the discovery files behave exactly as before on every host, and their install lines use the host the request came in on.
- `/assets/app.js`, `/assets/app.css` and `/assets/common.js` are the page's own files and the shared data layer. `/assets/stats.json` carries the counts below. On a host without a page, `/assets/*` is a 404.
- Responses carry `Vary: Host, X-Forwarded-Host`, because one URL is three pages.

## Where the numbers come from

The page source holds no counts. `/assets/stats.json` is computed from the database (read-only, once, then cached): entries and verified entries per kind, the conflicting-flag rows, plugin publisher tiers, recorded risk flags, licence and source counts, and the verified records. The page reads `/v1/kinds` and `/v1/categories` live and uses `/assets/stats.json` for what the API has no route for.

The same figures are embedded in the served HTML as a JSON data block (`id="hub-fallback"`) together with a small sample of records. The page falls back to it when a call fails, and says so. A test asserts that the page files contain no catalogue figures.

## Trust, shown plainly

- An entry is verified only when its record says `verified` and does not also say `quarantined`. Everything else is quarantined, and so is every plugin and connector.
- A plugin's publisher tier (Official, Certified, Community) is the upstream index's label, shown only where the record has one. It is not a review.
- A connector's risk flags are the flags recorded from its own disclosure. None recorded does not mean none exist.
- A quarantined entry has no copy button and no install line: its record line reads JSON and installs nothing.
- No page claims a certification, a customer or a guarantee.

## Safety of the page

- Record text is untrusted. Pages write it with `textContent` only; links are made only for `https://` URLs with `rel="noopener noreferrer nofollow"`.
- Page routes carry a strict Content-Security-Policy: `default-src 'none'`, scripts and data from the same origin, fonts and stylesheets from Google Fonts, no inline script or style, no framing. The API and the docs keep their existing policy.
- No new write route. POST is still refused on a read-only origin.

## API addition

`GET /v1/skills` takes an optional `category=<slug>` (with `kind`, `limit`, `offset`, `envelope`). Without it the response is unchanged.

## Decisions and what was rejected

- **Static files, not templates.** Each page is `index.html`, `app.css` and `app.js` under `hub/pages/<name>/`, with `hub/pages/shared/common.js`. A template engine would be a dependency for three pages.
- **Embedded data as a data block, not an inline script.** It keeps the strict policy free of `unsafe-inline` and hashes.
- **Stats from the database, not from the API.** The API has no route for the verified count or the tier counts. A new `/v1/*` route would change the contract; `/assets/stats.json` does not.
- **Rejected: an "All" tab.** The API lists one kind at a time. A mixed list would be a client-side merge of three paged queries.
- **Rejected: client-side filters that look server-side.** Source, licence and risk-flag filters work on the records loaded so far, and the page says so.
