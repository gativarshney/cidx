// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// The site is served from the domain root. Vercel supplies the production
// hostname at build time; SITE_URL and SITE_BASE override both, for a custom
// domain or a sub-path host such as GitHub Pages (see website/README.md).
const vercelHost = process.env.VERCEL_PROJECT_PRODUCTION_URL;
const site = process.env.SITE_URL ?? (vercelHost ? `https://${vercelHost}` : 'https://cidx.vercel.app');
const base = process.env.SITE_BASE ?? '/';

export default defineConfig({
	site,
	base,
	// Accept /page and /page/ alike in dev; the host redirects to the slash form.
	trailingSlash: 'ignore',
	redirects: { '/docs': '/docs/quickstart/' },
	integrations: [
		starlight({
			title: 'cidx',
			description:
				'cidx is a zero-config local code index for AI coding agents: tree-sitter parsing, a SQLite index kept fresh on every save, and five read-only MCP tools.',
			logo: { src: './src/assets/mark.svg', alt: '' },
			favicon: '/favicon.svg',
			social: [
				{ icon: 'github', label: 'GitHub', href: 'https://github.com/gativarshney/cidx' },
			],
			customCss: ['./src/styles/fonts.css', './src/styles/tokens.css', './src/styles/starlight.css'],
			sidebar: [
				{
					label: 'Start here',
					items: [{ label: 'Quickstart', slug: 'docs/quickstart' }],
				},
			],
		}),
	],
});
