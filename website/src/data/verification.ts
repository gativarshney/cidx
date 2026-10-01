// Numbers copied from docs/verification.md in this repository, which records
// the commands that produced them. Do not edit a value here without changing
// that file first: the site only repeats what the record states.

export const django = {
	source: 'docs/verification.md',
	measured: '2026-09-16',
	machine: 'Windows 11 laptop, Python 3.13.7',
	repository: 'django/django',
	commit: '2b30f6255b5ef84afbd827993643d52ef2c0963a',
	files: 3043,
	symbols: 76166,
	refs: 206801,
	coldIndexSeconds: 30.5, // empty cache, warm OS file cache
	coldIndexColdCacheSeconds: [67.8, 97.2],
	saveIsolatedSeconds: 0.33,
	saveBackToBackSeconds: 1.77, // p50 of 10 back-to-back saves
	targetQueryMs: 50,
	queries: [
		{ name: 'outline_file', p50: 0.1, p95: 0.3 },
		{ name: 'find_definition', p50: 16.3, p95: 22.6 },
		{ name: 'find_references', p50: 17.5, p95: 27.0 },
		{ name: 'repo_map', p50: 118.8, p95: 134.7 },
		{ name: 'search_symbols', p50: 107.5, p95: 138.8 },
	],
};

// `pytest -q` at the commit this site was built from.
export const tests = { count: 263, verified: '2026-10-01' };
