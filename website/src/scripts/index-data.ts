// Typed view of src/data/graph.json: definitions and resolved references from
// the index cidx built for pallets/click.

import graph from '../data/graph.json';

export interface IndexNode {
	name: string;
	kind: string;
	path: string;
	line: number;
	signature: string | null;
	/** References from inside another indexed definition (the graph's edges). */
	inbound: number;
	/** Every reference cidx resolved to this definition. */
	refs: number;
	/** The first few of those references: path, line, confidence. */
	sample: { path: string; line: number; confidence: string }[];
	file: number;
	p: number[];
}

const CONFIDENCE = ['exact', 'import', 'name-only'];
const files = graph.files as string[];

export const nodes: IndexNode[] = (graph.nodes as any[]).map((node) => ({
	name: node.name,
	kind: node.kind,
	path: files[node.file],
	line: node.line,
	signature: node.sig,
	inbound: node.inbound,
	refs: node.refs,
	sample: (node.sample as number[][]).map(([file, line, confidence]) => ({
		path: files[file],
		line,
		confidence: CONFIDENCE[confidence],
	})),
	file: node.file,
	p: node.p,
}));

/** [source node, target node, reference count, confidence code] */
export const edges = graph.edges as number[][];

const MATCH_EXACT = 3;
const MATCH_PREFIX = 2;
const MATCH_SUBSTRING = 1;

/**
 * Name search over the captured definitions. It follows the tiers cidx ranks
 * by (exact, then prefix, then substring) with reference count as the
 * tiebreak; cidx itself also weighs kind, locality and recency.
 */
export function search(text: string, limit = 5): number[] {
	const query = text.trim().toLowerCase();
	if (!query) return [];
	const matches: { index: number; tier: number }[] = [];
	nodes.forEach((node, index) => {
		const qualified = node.name.toLowerCase();
		const bare = qualified.slice(qualified.lastIndexOf('.') + 1);
		let tier = 0;
		if (qualified === query || bare === query) tier = MATCH_EXACT;
		else if (bare.startsWith(query) || qualified.startsWith(query)) tier = MATCH_PREFIX;
		else if (qualified.includes(query)) tier = MATCH_SUBSTRING;
		if (tier) matches.push({ index, tier });
	});
	return matches
		.sort((a, b) => b.tier - a.tier || nodes[b.index].refs - nodes[a.index].refs || a.index - b.index)
		.slice(0, limit)
		.map((match) => match.index);
}
