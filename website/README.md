# cidx website

The source of the cidx site: a static Astro build with Starlight for the
documentation pages. It lives next to the code so the docs change in the same
commit as the behavior they describe.

## Run it locally

Requires Node 22 or newer.

```bash
cd website
npm install
npm run dev
```

Open <http://localhost:4321/>.

## Commands

| Command | What it does |
|---|---|
| `npm run dev` | Dev server with live reload |
| `npm run build` | Production build into `dist/` |
| `npm run preview` | Serve the production build locally |
| `npm run check` | Type-check Astro and TypeScript files |
| `npm run capture -- --repo <click clone>` | Re-record the real cidx output the site displays |

## Where the content comes from

Nothing shown as output is typed by hand.

- `src/data/demo.json` and `src/data/graph.json` are written by
  `scripts/capture.mjs`. It runs the cidx CLI, drives `cidx serve` through the
  official MCP TypeScript client, and reads the index cidx built. Each file
  records the cidx version, repository, commit, machine, and date.
- `src/data/verification.ts` repeats numbers from `docs/verification.md`.
- The version comes from `../pyproject.toml`. The published version and the
  star count are read from the PyPI and GitHub APIs at build time and
  refreshed in the browser.

To re-record, clone `pallets/click` at the commit pinned in
`benchmark/datasets/manifest.json`, install cidx, then:

```bash
npm run capture -- --repo /path/to/click
```

## Layout

```
src/pages/        the landing page
src/components/   landing page sections
src/scripts/      the 3D symbol graph (three.js)
src/content/docs/ documentation pages (Starlight)
src/data/         captured output and recorded measurements
src/util/         shared helpers
scripts/          capture tooling
```
