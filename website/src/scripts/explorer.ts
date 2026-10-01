// The hero's query console: a live name search over the captured index of
// pallets/click, wired to the 3D graph. It runs in the browser on the data in
// src/data/graph.json; it is a demonstration of the index, not cidx itself.

import type { GraphController } from './graph';
import { nodes, search } from './index-data';

const AUTO_QUERIES = ['echo', 'Context', 'pass_context', 'Group', 'option', 'ParamType'];
const RESULT_LIMIT = 3;

const escapeHtml = (text: string) =>
	text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function supportsWebGL(): boolean {
	try {
		return Boolean(document.createElement('canvas').getContext('webgl2'));
	} catch {
		return false;
	}
}

export async function mountExplorer(hero: HTMLElement): Promise<void> {
	const root = hero.querySelector<HTMLElement>('[data-explorer]')!;
	const input = root.querySelector<HTMLInputElement>('[data-query]')!;
	const list = root.querySelector<HTMLElement>('[data-results]')!;
	const status = root.querySelector<HTMLElement>('[data-status]')!;
	const graphHost = hero.querySelector<HTMLElement>('[data-graph]');
	const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
	const totals = { files: Number(root.dataset.files) };
	const readyStatus = status.textContent ?? '';

	let graph: GraphController | null = null;
	let results: number[] = [];
	let active = -1; // node index of the highlighted result
	let auto = !reduceMotion;
	let typing = 0; // increments to cancel an auto-typed query in flight

	function setActive(index: number) {
		active = index;
		list.querySelectorAll<HTMLElement>('[data-node]').forEach((item) => {
			item.setAttribute('aria-selected', String(Number(item.dataset.node) === index));
		});
		graph?.select(index);
	}

	function render(query: string, preferred = -1) {
		results = search(query, RESULT_LIMIT);
		if (preferred !== -1 && !results.includes(preferred)) results = [preferred, ...results].slice(0, RESULT_LIMIT);
		list.innerHTML = results.length
			? results
					.map((index) => {
						const node = nodes[index];
						return `<li role="option" data-node="${index}" aria-selected="false"><strong>${escapeHtml(node.name)}</strong><span class="t-kind">${node.kind}</span><span class="t-loc">${escapeHtml(node.path)}:${node.line}</span></li>`;
					})
					.join('')
			: `<li class="empty">${query.trim() ? `No match among the ${nodes.length} definitions shown here.` : 'Type a function or class name.'}</li>`;
		graph?.highlight(results);
		setActive(results.length ? (preferred !== -1 ? preferred : results[0]) : -1);
	}

	const stopAuto = () => {
		auto = false;
		typing += 1;
		root.classList.remove('auto');
	};

	// --- visitor input ---------------------------------------------------

	input.addEventListener('input', () => render(input.value));
	input.addEventListener('keydown', (event) => {
		stopAuto();
		if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
		event.preventDefault();
		if (!results.length) return;
		const at = results.indexOf(active);
		const next = (at + (event.key === 'ArrowDown' ? 1 : results.length - 1)) % results.length;
		setActive(results[next]);
	});
	root.addEventListener('pointerdown', stopAuto);
	list.addEventListener('click', (event) => {
		const item = (event.target as HTMLElement).closest<HTMLElement>('[data-node]');
		if (item) setActive(Number(item.dataset.node));
	});

	render(input.value);

	// --- the graph -------------------------------------------------------

	let built = Promise.resolve();
	if (graphHost && supportsWebGL()) {
		try {
			const { mountGraph } = await import('./graph');
			graph = mountGraph(graphHost);
			graph.onPick((index) => {
				stopAuto();
				const name = nodes[index].name;
				input.value = name.slice(name.lastIndexOf('.') + 1);
				render(input.value, index);
			});
			if (!reduceMotion) {
				// while the graph assembles itself, the status line counts files in
				built = new Promise((resolve) => {
					graph!.onBuild((progress) => {
						if (progress >= 1) {
							status.textContent = readyStatus;
							root.classList.remove('building');
							resolve();
							return;
						}
						root.classList.add('building');
						const files = Math.round(progress * totals.files);
						status.textContent = `indexing ${files} / ${totals.files} files`;
					});
				});
			}
		} catch {
			graph = null; // the console still works without the 3D view
		}
	}

	await built;
	if (graph) {
		graph.highlight(results);
		graph.select(active);
	}

	// --- auto demo: type a few real queries until the visitor takes over --

	let inView = true;
	new IntersectionObserver(([entry]) => (inView = entry.isIntersecting), { threshold: 0.2 }).observe(root);

	async function autoType(query: string) {
		const token = ++typing;
		root.classList.add('auto');
		for (let length = input.value.length; length >= 0; length -= 1) {
			if (token !== typing) return;
			input.value = input.value.slice(0, length);
			await sleep(28);
		}
		for (let length = 1; length <= query.length; length += 1) {
			if (token !== typing) return;
			input.value = query.slice(0, length);
			render(input.value);
			await sleep(85);
		}
	}

	let turn = Math.max(AUTO_QUERIES.indexOf(input.value), 0);
	while (auto) {
		await sleep(5200);
		if (!auto) break;
		if (!inView || document.hidden || document.activeElement === input) continue;
		turn += 1;
		await autoType(AUTO_QUERIES[turn % AUTO_QUERIES.length]);
	}
}
