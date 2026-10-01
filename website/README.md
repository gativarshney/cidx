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

## Deployment

The site is hosted on Vercel at <https://cidx.vercel.app>. The Vercel project
is connected to this repository, and `vercel.json` at the repository root
holds the whole configuration: install and build inside `website/`, serve
`website/dist`, redirect every URL to its trailing-slash form.

- A push to `main` deploys to production, but only when the commit touches
  `website/`, `docs/`, `pyproject.toml`, or `vercel.json`.
- Other branches and pull requests get a preview URL.
- A release needs no extra step: the version bump in `pyproject.toml`
  triggers a build, and the published version shown on the page is also
  refreshed in the browser from the PyPI API.

To deploy by hand from the repository root:

```bash
vercel deploy --prod
```

### Custom domain

1. In the Vercel dashboard, open the `cidx` project, then Settings, Domains,
   and add the domain.
2. At your DNS provider, add the record Vercel shows (a CNAME to
   `cname.vercel-dns.com` for a subdomain, or an A record for an apex domain).
3. Mark the new domain as the production domain. The next build picks it up
   for canonical URLs and the sitemap with no code change.

To host somewhere that serves the site under a sub-path, build with
`SITE_URL` and `SITE_BASE` set, for example
`SITE_URL=https://gativarshney.github.io SITE_BASE=/cidx npm run build`.

## Where the content comes from

Nothing shown as output is typed by hand.

- `src/data/demo.json` and `src/data/graph.json` are written by
  `scripts/capture.mjs`. It runs the cidx CLI, drives `cidx serve` through the
  official MCP TypeScript client, and reads the index cidx built. Each file
  records the cidx version, repository, commit, machine, and date.
- `src/data/verification.ts` repeats numbers from `docs/verification.md`.
- The version comes from `../pyproject.toml`. The published version is read
  from the PyPI API at build time and refreshed in the browser.

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
