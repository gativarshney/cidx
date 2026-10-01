import { readFileSync } from 'node:fs';
import path from 'node:path';

export const REPO_URL = 'https://github.com/gativarshney/cidx';
export const PYPI_URL = 'https://pypi.org/project/cidx/';
export const LICENSE_URL = `${REPO_URL}/blob/main/LICENSE`;
export const AUTHOR = {
	name: 'Gati Varshney',
	linkedin: 'https://linkedin.com/in/gativarshney',
	github: 'https://github.com/gativarshney',
	portfolio: 'https://gativarshney.github.io',
};

const base = import.meta.env.BASE_URL.replace(/\/$/, '');

/** Prefix an internal path with the deploy base (`/cidx` on GitHub Pages). */
export function href(path: string): string {
	return `${base}${path.startsWith('/') ? path : `/${path}`}`;
}

/** The version in ../pyproject.toml: what the docs on this site describe. */
export function sourceVersion(): string {
	// astro runs from website/, one level below the repository root
	const pyproject = readFileSync(path.resolve(process.cwd(), '..', 'pyproject.toml'), 'utf8');
	const match = pyproject.match(/^version\s*=\s*"([^"]+)"/m);
	if (!match) throw new Error('could not read the version from pyproject.toml');
	return match[1];
}

async function fetchJson(url: string): Promise<any | null> {
	try {
		const response = await fetch(url, { signal: AbortSignal.timeout(8000) });
		return response.ok ? await response.json() : null;
	} catch {
		return null; // offline builds still succeed; the page refreshes these in the browser
	}
}

export interface LiveMeta {
	pypiVersion: string | null;
}

let cached: Promise<LiveMeta> | undefined;

/** The published version, read once per build from the PyPI API. */
export function liveMeta(): Promise<LiveMeta> {
	cached ??= (async () => {
		const pypi = await fetchJson('https://pypi.org/pypi/cidx/json');
		return { pypiVersion: typeof pypi?.info?.version === 'string' ? pypi.info.version : null };
	})();
	return cached;
}
