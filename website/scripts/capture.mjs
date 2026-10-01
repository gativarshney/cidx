// Captures everything the site shows as "real output" by running cidx.
//
// Nothing on the site is typed by hand: this script runs the CLI, drives
// `cidx serve` through the official MCP TypeScript client, reads the index
// it built, and writes the results to src/data/*.json with provenance
// (cidx version, repository, commit, machine, date).
//
// Usage:
//   node scripts/capture.mjs --repo <path to a clone of pallets/click> [--cidx <cidx executable>]
//
// The repository is edited once (one appended line in src/click/utils.py)
// to measure the watcher, and restored before the script exits.

import { execFileSync, spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

const args = process.argv.slice(2);
const option = (name, fallback) => {
	const at = args.indexOf(`--${name}`);
	return at === -1 ? fallback : args[at + 1];
};
const cidx = option('cidx', 'cidx');
const repo = path.resolve(option('repo', '.'));
const outDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src', 'data');
mkdirSync(outDir, { recursive: true });

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const estimateTokens = (text) => Math.floor(text.length / 4); // the estimate cidx itself uses

function run(argv) {
	const started = performance.now();
	const result = spawnSync(cidx, argv, { cwd: repo, encoding: 'utf8' });
	const ms = Math.round(performance.now() - started);
	const output = (result.stdout + result.stderr).replace(/\r\n/g, '\n').trimEnd();
	return { command: `cidx ${argv.join(' ')}`, output, exit: result.status, ms };
}

function git(argv) {
	return execFileSync('git', argv, { cwd: repo, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
}

// --- provenance ---------------------------------------------------------

const provenance = {
	cidx: run(['--version']).output,
	repository: 'pallets/click',
	commit: git(['rev-parse', 'HEAD']).trim(),
	captured: new Date().toISOString().slice(0, 10),
	machine: {
		os: `${os.type()} ${os.release()}`,
		cpu: os.cpus()[0].model.trim(),
		cores: os.cpus().length,
		memoryGb: Math.round(os.totalmem() / 2 ** 30),
		node: process.version,
	},
};
if (git(['status', '--porcelain']).trim()) {
	throw new Error(`${repo} has uncommitted changes; capture needs a clean checkout`);
}

// --- CLI ----------------------------------------------------------------

const cli = {
	help: run(['--help']),
	index: run(['index', '--repo', '.']),
	stats: run(['stats', '--repo', '.']),
	definition: run(['query', 'Context', '--repo', '.']),
	qualified: run(['query', 'Context.invoke', '--repo', '.']),
	fuzzy: run(['query', 'pass_cont', '--repo', '.']),
	references: run(['query', 'echo', '--references', '--limit', '8', '--repo', '.']),
	outline: run(['query', 'src/click/globals.py', '--outline', '--repo', '.']),
	repoMap: run(['query', '--repo-map', '--limit', '5', '--repo', '.']),
	json: run(['query', 'Context', '--json', '--repo', '.']),
	miss: run(['query', 'no_such_symbol', '--repo', '.']),
	check: run(['check', '--repo', '.']),
};
for (const [name, entry] of Object.entries(cli)) {
	if (entry.exit !== 0) throw new Error(`${name} exited ${entry.exit}: ${entry.output}`);
}
const dbPath = JSON.parse(run(['stats', '--json', '--repo', '.']).output).db;

// --- MCP: the five tools, then a live edit through the watcher -----------

const transport = new StdioClientTransport({
	command: cidx,
	args: ['serve', '--repo', repo],
	stderr: 'ignore',
});
const client = new Client({ name: 'cidx-site-capture', version: '1.0.0' });
await client.connect(transport);
const listed = await client.listTools();
const tools = listed.tools.map((tool) => ({
	name: tool.name,
	description: tool.description,
	inputSchema: tool.inputSchema,
}));

async function call(name, toolArguments) {
	const started = performance.now();
	const result = await client.callTool({ name, arguments: toolArguments });
	const ms = Math.round(performance.now() - started);
	const text = result.content?.[0]?.text ?? '';
	return { tool: name, arguments: toolArguments, text, isError: Boolean(result.isError), ms, tokens: estimateTokens(text) };
}

await sleep(5000); // the watcher's first reconciliation sweep
const mcp = {
	tools,
	repoMap: await call('repo_map', { max_tokens: 250 }),
	search: await call('search_symbols', { query: 'pass_cont' }),
	definition: await call('find_definition', { name: 'Context.invoke' }),
	references: await call('find_references', { name: 'echo' }),
	outline: await call('outline_file', { path: 'src/click/core.py' }),
	outlineSmall: await call('outline_file', { path: 'src/click/globals.py' }),
	miss: await call('find_definition', { name: 'no_such_symbol' }),
};

// The budget slider on the site re-trims these rows in the browser. The trim is a
// port of cidx.ranking.budget.shape, so prove here that it reproduces what the
// real server returned at two different budgets before publishing it.
const referenceRows = JSON.parse(run(['query', 'echo', '--references', '--limit', '200', '--json', '--repo', '.']).output);
const budgetLines = referenceRows.map(
	(row) =>
		`${row.path}:${row.line}  ${row.name}  [${row.confidence}]` +
		(row.resolved_qualified_name ? `  -> ${row.resolved_qualified_name} (${row.resolved_path})` : ''),
);
const shape = (lines, total, maxTokens) => {
	const kept = [];
	let spent = 0;
	for (const line of lines) {
		const cost = Math.max(1, Math.floor(line.length / 4));
		if (kept.length && spent + cost > maxTokens) break;
		kept.push(line);
		spent += cost;
	}
	return kept.length < total ? [...kept, `truncated: true, total_matches: ${total}`] : kept;
};
for (const maxTokens of [150, 700]) {
	const real = await call('find_references', { name: 'echo', max_tokens: maxTokens });
	const expected = real.text.split('\n').filter((line) => !line.startsWith('index_age_ms'));
	const ported = shape(budgetLines, budgetLines.length, maxTokens);
	if (JSON.stringify(expected) !== JSON.stringify(ported)) {
		throw new Error(`budget port disagrees with the server at max_tokens=${maxTokens}`);
	}
}
const budget = { tool: 'find_references', name: 'echo', total: budgetLines.length, lines: budgetLines, verifiedAt: [150, 700] };

const target = path.join(repo, 'src', 'click', 'utils.py');
const original = readFileSync(target);
const appended = '\n\ndef live_demo_symbol(): pass\n';
const live = { edit: `echo "def live_demo_symbol(): pass" >> src/click/utils.py`, samplesMs: [] };
try {
	for (let round = 0; round < 5; round += 1) {
		live.before = await call('find_definition', { name: 'live_demo_symbol' });
		writeFileSync(target, Buffer.concat([original, Buffer.from(appended)]));
		const saved = performance.now();
		for (;;) {
			const answer = await call('find_definition', { name: 'live_demo_symbol' });
			if (answer.text.includes('utils.py')) {
				live.samplesMs.push(Math.round(performance.now() - saved));
				live.after = answer;
				break;
			}
			if (performance.now() - saved > 60000) throw new Error('watcher never indexed the edit');
			await sleep(25);
		}
		writeFileSync(target, original);
		for (;;) {
			const answer = await call('find_definition', { name: 'live_demo_symbol' });
			if (!answer.text.includes('utils.py')) break;
			await sleep(25);
		}
		await sleep(1500); // let the save settle so samples are isolated
	}
} finally {
	writeFileSync(target, original);
}
live.samplesMs.sort((a, b) => a - b);
live.medianMs = live.samplesMs[Math.floor(live.samplesMs.length / 2)];
await client.close();
await sleep(500);
live.check = run(['check', '--repo', '.']);

// --- the same two questions answered without an index --------------------

const grepEcho = git(['grep', '-n', 'echo']);
const coreSource = readFileSync(path.join(repo, 'src', 'click', 'core.py'), 'utf8');
const baseline = {
	grep: {
		command: 'git grep -n echo',
		lines: grepEcho.trimEnd().split('\n').length,
		chars: grepEcho.length,
		tokens: estimateTokens(grepEcho),
		sample: grepEcho.split('\n').slice(0, 9),
	},
	readFile: {
		command: 'cat src/click/core.py',
		lines: coreSource.split('\n').length,
		chars: coreSource.length,
		tokens: estimateTokens(coreSource),
	},
};

writeFileSync(
	path.join(outDir, 'demo.json'),
	JSON.stringify({ provenance, cli, mcp, live, baseline, budget }, null, '\t') + '\n',
);

// --- graph: real symbols and resolved references from the index ----------

const db = new DatabaseSync(dbPath, { readOnly: true });
const counts = {
	files: db.prepare('SELECT COUNT(*) AS n FROM files').get().n,
	symbols: db.prepare('SELECT COUNT(*) AS n FROM symbols').get().n,
	refs: db.prepare('SELECT COUNT(*) AS n FROM refs').get().n,
	resolved: db.prepare('SELECT COUNT(*) AS n FROM refs WHERE resolved_symbol_id IS NOT NULL').get().n,
	byConfidence: Object.fromEntries(
		db.prepare('SELECT confidence, COUNT(*) AS n FROM refs GROUP BY confidence').all().map((row) => [row.confidence, row.n]),
	),
};

const symbols = db
	.prepare(
		`SELECT s.id, s.name, s.qualified_name AS qname, s.kind, s.start_line AS line,
		        s.end_line AS endLine, s.file_id AS fileId, f.path, s.signature
		 FROM symbols s JOIN files f ON f.id = s.file_id
		 WHERE s.kind IN ('function', 'class', 'method', 'const')`,
	)
	.all();
const byFile = new Map();
for (const symbol of symbols) {
	if (!byFile.has(symbol.fileId)) byFile.set(symbol.fileId, []);
	byFile.get(symbol.fileId).push(symbol);
}
const enclosing = (fileId, line) => {
	let best = null;
	for (const symbol of byFile.get(fileId) ?? []) {
		if (symbol.kind === 'const') continue;
		if (symbol.line <= line && line <= symbol.endLine && (!best || symbol.line >= best.line)) best = symbol;
	}
	return best;
};

// an edge is "the definition enclosing a reference" -> "the definition it resolved to"
const edgeCounts = new Map();
const inbound = new Map();
const referenceCount = new Map(); // every reference resolved to a symbol
const referenceSample = new Map(); // the first few, in the order find_references returns them
for (const ref of db
	.prepare(
		`SELECT r.file_id AS fileId, r.line, r.resolved_symbol_id AS target, r.confidence, f.path
		 FROM refs r JOIN files f ON f.id = r.file_id
		 WHERE r.resolved_symbol_id IS NOT NULL ORDER BY f.path, r.line`,
	)
	.all()) {
	referenceCount.set(ref.target, (referenceCount.get(ref.target) ?? 0) + 1);
	const sample = referenceSample.get(ref.target) ?? [];
	if (sample.length < 4) sample.push({ path: ref.path, line: ref.line, confidence: ref.confidence });
	referenceSample.set(ref.target, sample);
	const source = enclosing(ref.fileId, ref.line);
	if (!source || source.id === ref.target) continue;
	const key = `${source.id}>${ref.target}`;
	const edge = edgeCounts.get(key) ?? { source: source.id, target: ref.target, count: 0, confidence: ref.confidence };
	edge.count += 1;
	edgeCounts.set(key, edge);
	inbound.set(ref.target, (inbound.get(ref.target) ?? 0) + 1);
}
db.close();

const symbolById = new Map(symbols.map((symbol) => [symbol.id, symbol]));
const inLibrary = (symbol) => symbol && symbol.path.startsWith('src/');
const NODE_CAP = 420;
const ranked = [...inbound.entries()]
	.filter(([id]) => inLibrary(symbolById.get(id)))
	.sort((a, b) => b[1] - a[1] || a[0] - b[0]);
const keep = new Set(ranked.slice(0, 260).map(([id]) => id));
const libraryEdges = [...edgeCounts.values()]
	.filter((edge) => inLibrary(symbolById.get(edge.source)) && keep.has(edge.target))
	.sort((a, b) => b.count - a.count || a.source - b.source);
for (const edge of libraryEdges) {
	if (keep.size >= NODE_CAP) break;
	keep.add(edge.source);
}
const edges = libraryEdges.filter((edge) => keep.has(edge.source) && keep.has(edge.target));

// deterministic 3D force layout: springs on edges, repulsion, pull to file centre
let seed = 20260728;
const random = () => {
	seed = (seed * 1664525 + 1013904223) % 4294967296;
	return seed / 4294967296;
};
const ids = [...keep];
const indexOf = new Map(ids.map((id, index) => [id, index]));
const files = [...new Set(ids.map((id) => symbolById.get(id).path))].sort();
// files that only appear as the location of a reference go after the laid-out ones
const allFiles = [...files];
const fileIndex = (file) => {
	let at = allFiles.indexOf(file);
	if (at === -1) at = allFiles.push(file) - 1;
	return at;
};
const confidenceCode = (confidence) => (confidence === 'exact' ? 0 : confidence === 'import' ? 1 : 2);
const fileCentre = new Map(
	files.map((file, index) => {
		const phi = Math.acos(1 - (2 * (index + 0.5)) / files.length);
		const theta = Math.PI * (1 + Math.sqrt(5)) * index;
		return [file, [Math.sin(phi) * Math.cos(theta) * 70, Math.cos(phi) * 70, Math.sin(phi) * Math.sin(theta) * 70]];
	}),
);
const position = ids.map((id) => fileCentre.get(symbolById.get(id).path).map((value) => value + (random() - 0.5) * 30));
const links = edges.map((edge) => [indexOf.get(edge.source), indexOf.get(edge.target), edge.count]);
for (let step = 0; step < 320; step += 1) {
	const cooling = 1 - step / 320;
	const force = position.map(() => [0, 0, 0]);
	for (let a = 0; a < ids.length; a += 1) {
		for (let b = a + 1; b < ids.length; b += 1) {
			const delta = [0, 1, 2].map((axis) => position[a][axis] - position[b][axis]);
			const distanceSquared = Math.max(delta[0] ** 2 + delta[1] ** 2 + delta[2] ** 2, 1);
			const push = 14 / distanceSquared;
			for (let axis = 0; axis < 3; axis += 1) {
				force[a][axis] += delta[axis] * push;
				force[b][axis] -= delta[axis] * push;
			}
		}
	}
	for (const [a, b, weight] of links) {
		const strength = 0.012 * Math.min(1 + Math.log2(weight), 4);
		for (let axis = 0; axis < 3; axis += 1) {
			const delta = position[b][axis] - position[a][axis];
			force[a][axis] += delta * strength;
			force[b][axis] -= delta * strength;
		}
	}
	ids.forEach((id, index) => {
		const centre = fileCentre.get(symbolById.get(id).path);
		for (let axis = 0; axis < 3; axis += 1) {
			force[index][axis] += (centre[axis] - position[index][axis]) * 0.035;
			const move = Math.max(-4, Math.min(4, force[index][axis])) * cooling;
			position[index][axis] += move;
		}
	});
}

const graphNodes = ids.map((id, index) => {
		const symbol = symbolById.get(id);
		return {
			name: symbol.qname,
			kind: symbol.kind,
			file: files.indexOf(symbol.path),
			line: symbol.line,
			sig: symbol.signature,
			inbound: inbound.get(id) ?? 0,
			refs: referenceCount.get(id) ?? 0,
			sample: (referenceSample.get(id) ?? []).map((ref) => [fileIndex(ref.path), ref.line, confidenceCode(ref.confidence)]),
			p: position[index].map((value) => Math.round(value * 10) / 10),
		};
});
const graph = {
	provenance,
	counts,
	files: allFiles,
	layoutFiles: files.length,
	nodes: graphNodes,
	edges: edges.map((edge) => [indexOf.get(edge.source), indexOf.get(edge.target), edge.count, confidenceCode(edge.confidence)]),
};
writeFileSync(path.join(outDir, 'graph.json'), JSON.stringify(graph) + '\n');

console.log(`cidx: ${provenance.cidx}`);
console.log(`index: ${counts.files} files, ${counts.symbols} symbols, ${counts.refs} refs`);
console.log(`graph: ${graph.nodes.length} nodes, ${graph.edges.length} edges`);
console.log(`save -> queryable: ${live.samplesMs.join(', ')} ms (median ${live.medianMs})`);
console.log(`grep echo: ${baseline.grep.lines} lines, ~${baseline.grep.tokens} tokens; references via cidx: ~${mcp.references.tokens} tokens`);
console.log(`cat core.py: ~${baseline.readFile.tokens} tokens; outline via cidx: ~${mcp.outline.tokens} tokens`);
