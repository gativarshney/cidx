// The hero's 3D symbol graph. Every node is a real definition from the index
// cidx built for pallets/click, and every edge is a reference cidx resolved
// (src/data/graph.json, written by scripts/capture.mjs).

import {
	AdditiveBlending,
	BufferAttribute,
	BufferGeometry,
	Color,
	Group,
	LineBasicMaterial,
	LineSegments,
	NormalBlending,
	PerspectiveCamera,
	Points,
	Scene,
	ShaderMaterial,
	Vector3,
	WebGLRenderer,
} from 'three';
import { edges, nodes } from './index-data';

const LABELS = 10;
const PULSES = 64;
const DUST = 420;
const BUILD_SECONDS = 2.6;

const nodeVertex = /* glsl */ `
	attribute float size;
	attribute vec3 color;
	attribute float phase;
	attribute float birth;
	attribute float lit;
	uniform float uTime;
	uniform float uPixelRatio;
	uniform float uBuild;
	uniform float uDim;
	uniform float uDistance;
	uniform float uSolid;
	varying vec3 vColor;
	varying float vAlpha;
	void main() {
		vec4 mv = modelViewMatrix * vec4(position, 1.0);
		float born = step(birth, uBuild);
		float pop = 1.0 + 1.6 * exp(-(uBuild - birth) * 26.0);
		float breathe = 1.0 + 0.12 * sin(uTime * 1.6 + phase);
		float emphasis = mix(1.0, mix(0.8, 1.8, lit), uDim);
		gl_PointSize = size * mix(1.0, 0.55, uSolid) * born * pop * breathe * emphasis
			* uPixelRatio * (uDistance * 0.8 / -mv.z);
		gl_Position = projectionMatrix * mv;
		vColor = color;
		float depth = smoothstep(uDistance + 110.0, uDistance - 140.0, -mv.z);
		vAlpha = born * mix(0.28, 1.0, depth) * mix(1.0, mix(0.34, 1.0, lit), uDim);
	}
`;

const nodeFragment = /* glsl */ `
	uniform float uSolid;
	varying vec3 vColor;
	varying float vAlpha;
	void main() {
		float d = length(gl_PointCoord - 0.5);
		if (d > 0.5) discard;
		float core = smoothstep(0.2, 0.06, d);
		float glow = pow(1.0 - d * 2.0, 2.0);
		float solid = smoothstep(0.5, 0.4, d);
		vec3 colour = mix(vColor + core * 0.6, vColor, uSolid);
		gl_FragColor = vec4(colour, mix(glow, solid, uSolid) * vAlpha);
	}
`;

// an expanding ring around the selected node
const ringFragment = /* glsl */ `
	uniform float uTime;
	varying vec3 vColor;
	varying float vAlpha;
	void main() {
		float d = length(gl_PointCoord - 0.5) * 2.0;
		float wave = fract(uTime * 0.7);
		float ring = smoothstep(0.07, 0.0, abs(d - wave)) * (1.0 - wave);
		float halo = smoothstep(0.06, 0.0, abs(d - 0.42));
		float alpha = max(ring, halo * 0.9);
		if (alpha < 0.01) discard;
		gl_FragColor = vec4(vColor, alpha);
	}
`;

export interface GraphController {
	/** Focus one node (camera turns to it, its references light up), or -1 to clear. */
	select(index: number): void;
	/** Dim everything except these nodes; an empty list restores the full graph. */
	highlight(indices: number[]): void;
	/** Called when the visitor clicks a node. */
	onPick(listener: (index: number) => void): void;
	/** Called with 0..1 while the graph assembles itself. */
	onBuild(listener: (progress: number) => void): void;
	destroy(): void;
}

export function mountGraph(host: HTMLElement): GraphController {
	const canvas = host.querySelector('canvas')!;
	const tooltip = host.querySelector<HTMLElement>('[data-graph-tip]')!;
	const labelLayer = host.querySelector<HTMLElement>('[data-graph-labels]')!;
	const hero = host.closest<HTMLElement>('section') ?? host;
	const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

	const renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
	const scene = new Scene();
	const camera = new PerspectiveCamera(42, 1, 1, 3000);
	const world = new Group();
	const dustGroup = new Group();
	scene.add(dustGroup, world);

	// --- nodes -----------------------------------------------------------

	const radius = Math.max(...nodes.map((node) => Math.hypot(node.p[0], node.p[1], node.p[2])));
	const scale = 105 / radius;
	const count = nodes.length;
	const positions = new Float32Array(count * 3);
	const sizes = new Float32Array(count);
	const phases = new Float32Array(count);
	const births = new Float32Array(count);
	const lit = new Float32Array(count);
	const nodeColors = new Float32Array(count * 3);
	const fileCount = Math.max(...nodes.map((node) => node.file)) + 1;
	nodes.forEach((node, index) => {
		positions.set([node.p[0] * scale, node.p[1] * scale, node.p[2] * scale], index * 3);
		sizes[index] = 7 + Math.log2(1 + node.inbound) * 3.4;
		phases[index] = (index * 2.399) % (Math.PI * 2);
		// files are "indexed" one after another; symbols in a file arrive together
		births[index] = (node.file / fileCount) * 0.82 + ((index * 0.618) % 1) * 0.08;
	});
	const nodeGeometry = new BufferGeometry();
	nodeGeometry.setAttribute('position', new BufferAttribute(positions, 3));
	nodeGeometry.setAttribute('size', new BufferAttribute(sizes, 1));
	nodeGeometry.setAttribute('phase', new BufferAttribute(phases, 1));
	nodeGeometry.setAttribute('birth', new BufferAttribute(births, 1));
	nodeGeometry.setAttribute('lit', new BufferAttribute(lit, 1));
	nodeGeometry.setAttribute('color', new BufferAttribute(nodeColors, 3));
	const uniforms = {
		uTime: { value: 0 },
		uPixelRatio: { value: 1 },
		uBuild: { value: reduceMotion ? 2 : 0 },
		uDim: { value: 0 },
		uSolid: { value: 0 },
		uDistance: { value: 330 },
	};
	const nodeMaterial = new ShaderMaterial({
		uniforms,
		vertexShader: nodeVertex,
		fragmentShader: nodeFragment,
		transparent: true,
		depthWrite: false,
	});
	world.add(new Points(nodeGeometry, nodeMaterial));

	// --- edges -----------------------------------------------------------

	const edgePositions = new Float32Array(edges.length * 6);
	const edgeColors = new Float32Array(edges.length * 6);
	edges.forEach(([source, target], index) => {
		edgePositions.set(positions.subarray(source * 3, source * 3 + 3), index * 6);
		edgePositions.set(positions.subarray(target * 3, target * 3 + 3), index * 6 + 3);
	});
	const edgeGeometry = new BufferGeometry();
	edgeGeometry.setAttribute('position', new BufferAttribute(edgePositions, 3));
	edgeGeometry.setAttribute('color', new BufferAttribute(edgeColors, 3));
	const edgeMaterial = new LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0, depthWrite: false });
	world.add(new LineSegments(edgeGeometry, edgeMaterial));

	const adjacency: number[][] = nodes.map(() => []);
	edges.forEach(([source, target], index) => {
		adjacency[source].push(index);
		adjacency[target].push(index);
	});

	// the selected or hovered node's references, drawn bright on top
	const FOCUS_MAX = 96;
	const focusPositions = new Float32Array(FOCUS_MAX * 6);
	const focusColors = new Float32Array(FOCUS_MAX * 6);
	const focusGeometry = new BufferGeometry();
	focusGeometry.setAttribute('position', new BufferAttribute(focusPositions, 3));
	focusGeometry.setAttribute('color', new BufferAttribute(focusColors, 3));
	focusGeometry.setDrawRange(0, 0);
	const focusMaterial = new LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.95, depthWrite: false });
	world.add(new LineSegments(focusGeometry, focusMaterial));

	// pulses travel along reference edges, from the caller to the definition
	const pulsePositions = new Float32Array(PULSES * 3);
	const pulseColors = new Float32Array(PULSES * 3);
	const pulseGeometry = new BufferGeometry();
	pulseGeometry.setAttribute('position', new BufferAttribute(pulsePositions, 3));
	pulseGeometry.setAttribute('color', new BufferAttribute(pulseColors, 3));
	pulseGeometry.setAttribute('size', new BufferAttribute(new Float32Array(PULSES).fill(6.5), 1));
	pulseGeometry.setAttribute('phase', new BufferAttribute(new Float32Array(PULSES), 1));
	pulseGeometry.setAttribute('birth', new BufferAttribute(new Float32Array(PULSES).fill(0.9), 1));
	pulseGeometry.setAttribute('lit', new BufferAttribute(new Float32Array(PULSES).fill(1), 1));
	const pulses = Array.from({ length: PULSES }, (_, index) => ({
		edge: (index * 37) % edges.length,
		t: (index * 0.137) % 1,
		speed: 0.35 + ((index * 0.61) % 1) * 0.5,
	}));
	const pulsePoints = new Points(pulseGeometry, nodeMaterial);
	pulsePoints.visible = false;
	world.add(pulsePoints);

	// ring around the selected node
	const ringGeometry = new BufferGeometry();
	ringGeometry.setAttribute('position', new BufferAttribute(new Float32Array(3), 3));
	ringGeometry.setAttribute('size', new BufferAttribute(new Float32Array([58]), 1));
	ringGeometry.setAttribute('phase', new BufferAttribute(new Float32Array(1), 1));
	ringGeometry.setAttribute('birth', new BufferAttribute(new Float32Array(1), 1));
	ringGeometry.setAttribute('lit', new BufferAttribute(new Float32Array([1]), 1));
	ringGeometry.setAttribute('color', new BufferAttribute(new Float32Array(3), 3));
	const ringMaterial = new ShaderMaterial({
		uniforms,
		vertexShader: nodeVertex,
		fragmentShader: ringFragment,
		transparent: true,
		depthWrite: false,
		depthTest: false,
	});
	const ring = new Points(ringGeometry, ringMaterial);
	ring.visible = false;
	world.add(ring);

	// faint dust far behind the graph, for depth
	const dustPositions = new Float32Array(DUST * 3);
	let seed = 7;
	const random = () => {
		seed = (seed * 1664525 + 1013904223) % 4294967296;
		return seed / 4294967296;
	};
	for (let index = 0; index < DUST; index += 1) {
		const distance = 170 + random() * 260;
		const theta = random() * Math.PI * 2;
		const phi = Math.acos(2 * random() - 1);
		dustPositions.set(
			[distance * Math.sin(phi) * Math.cos(theta), distance * Math.cos(phi), distance * Math.sin(phi) * Math.sin(theta)],
			index * 3,
		);
	}
	const dustGeometry = new BufferGeometry();
	const dustColors = new Float32Array(DUST * 3);
	dustGeometry.setAttribute('position', new BufferAttribute(dustPositions, 3));
	dustGeometry.setAttribute('color', new BufferAttribute(dustColors, 3));
	dustGeometry.setAttribute('size', new BufferAttribute(Float32Array.from({ length: DUST }, () => 1.6 + random() * 2.4), 1));
	dustGeometry.setAttribute('phase', new BufferAttribute(Float32Array.from({ length: DUST }, () => random() * 6.28), 1));
	dustGeometry.setAttribute('birth', new BufferAttribute(new Float32Array(DUST), 1));
	dustGeometry.setAttribute('lit', new BufferAttribute(new Float32Array(DUST).fill(1), 1));
	dustGroup.add(new Points(dustGeometry, nodeMaterial));

	// --- state -----------------------------------------------------------

	let selected = -1;
	let hovered = -1;
	let highlighted: number[] = [];
	let dimTarget = 0;
	let yaw = 0.4; // the rotation the visitor or the selection is steering toward
	let pitch = 0.12;
	let spin = reduceMotion ? 0 : 0.003;
	let steering = false; // true while easing toward a selected node
	let restYaw = 0; // where a selected node comes to rest, relative to dead centre
	let restPitch = 0;
	let parallaxX = 0;
	let parallaxY = 0;
	let pointerX = 0;
	let pointerY = 0;
	let dragging = false;
	let moved = 0;
	let lastX = 0;
	let lastY = 0;
	let pointer: { x: number; y: number } | null = null;
	const pickListeners: ((index: number) => void)[] = [];
	const buildListeners: ((progress: number) => void)[] = [];

	// --- labels ----------------------------------------------------------

	const topNodes = nodes
		.map((node, index) => ({ index, inbound: node.inbound }))
		.sort((a, b) => b.inbound - a.inbound)
		.slice(0, LABELS - 1)
		.map((entry) => entry.index);
	const labels = Array.from({ length: LABELS }, () => {
		const element = document.createElement('span');
		labelLayer.append(element);
		return element;
	});
	let labelled: number[] = topNodes;
	function setLabelled(indices: number[]) {
		labelled = indices.slice(0, LABELS);
		labels.forEach((label, slot) => {
			const index = labelled[slot];
			label.textContent = index === undefined ? '' : nodes[index].name;
			label.classList.toggle('strong', index !== undefined && index === selected);
		});
	}

	function refreshLit() {
		lit.fill(0);
		if (selected !== -1) {
			lit[selected] = 1;
			for (const edge of adjacency[selected]) {
				lit[edges[edge][0]] = 1;
				lit[edges[edge][1]] = 1;
			}
		}
		for (const index of highlighted) lit[index] = 1;
		if (hovered !== -1) lit[hovered] = 1;
		nodeGeometry.attributes.lit.needsUpdate = true;
		dimTarget = selected !== -1 || highlighted.length ? 1 : 0;
	}

	const edgePalette = [new Color(), new Color(), new Color()];
	function refreshFocus() {
		const centre = selected !== -1 ? selected : hovered;
		if (centre === -1) {
			focusGeometry.setDrawRange(0, 0);
			return;
		}
		const list = adjacency[centre].slice(0, FOCUS_MAX);
		list.forEach((edge, slot) => {
			const [source, target, , confidence] = edges[edge];
			focusPositions.set(positions.subarray(source * 3, source * 3 + 3), slot * 6);
			focusPositions.set(positions.subarray(target * 3, target * 3 + 3), slot * 6 + 3);
			edgePalette[confidence].toArray(focusColors, slot * 6);
			edgePalette[confidence].toArray(focusColors, slot * 6 + 3);
		});
		focusGeometry.attributes.position.needsUpdate = true;
		focusGeometry.attributes.color.needsUpdate = true;
		focusGeometry.setDrawRange(0, list.length * 2);
	}

	function select(index: number) {
		selected = index;
		ring.visible = index !== -1;
		if (index !== -1) {
			const [x, y, z] = positions.subarray(index * 3, index * 3 + 3);
			(ringGeometry.attributes.position.array as Float32Array).set([x, y, z]);
			ringGeometry.attributes.position.needsUpdate = true;
			// turn the graph so the node faces the camera
			const targetYaw = Math.atan2(-x, z) + restYaw;
			yaw += Math.atan2(Math.sin(targetYaw - yaw), Math.cos(targetYaw - yaw));
			pitch = Math.max(-1.1, Math.min(0.7, Math.atan2(y, Math.hypot(x, z)) + restPitch));
			steering = true;
			// pulses now carry this node's references
			const list = adjacency[index];
			if (list.length) pulses.forEach((pulse, slot) => (pulse.edge = list[slot % list.length]));
			const neighbours = [...new Set(list.flatMap((edge) => [edges[edge][0], edges[edge][1]]))]
				.filter((other) => other !== index)
				.sort((a, b) => nodes[b].inbound - nodes[a].inbound);
			setLabelled([index, ...neighbours]);
		} else {
			steering = false;
			setLabelled(highlighted.length ? highlighted : topNodes);
		}
		refreshLit();
		refreshFocus();
	}

	function highlight(indices: number[]) {
		highlighted = indices;
		if (selected === -1) setLabelled(indices.length ? indices : topNodes);
		refreshLit();
	}

	// --- theme -----------------------------------------------------------

	let edgeBaseOpacity = 0.26;
	function applyTheme() {
		const styles = getComputedStyle(document.documentElement);
		const read = (name: string) => new Color(styles.getPropertyValue(name).trim());
		const light = document.documentElement.dataset.theme === 'light';
		const kinds: Record<string, Color> = {
			class: read('--g-class'),
			function: read('--g-function'),
			method: read('--g-method'),
			const: read('--g-const'),
		};
		nodes.forEach((node, index) => (kinds[node.kind] ?? kinds.function).toArray(nodeColors, index * 3));
		nodeGeometry.attributes.color.needsUpdate = true;

		edgePalette[0] = read('--exact');
		edgePalette[1] = read('--import');
		edgePalette[2] = read('--name-only');
		edges.forEach((edge, index) => {
			edgePalette[edge[3]].toArray(edgeColors, index * 6);
			edgePalette[edge[3]].toArray(edgeColors, index * 6 + 3);
		});
		edgeGeometry.attributes.color.needsUpdate = true;

		const dust = read('--muted').multiplyScalar(light ? 1 : 0.55);
		for (let index = 0; index < DUST; index += 1) dust.toArray(dustColors, index * 3);
		dustGeometry.attributes.color.needsUpdate = true;
		read('--text').toArray(ringGeometry.attributes.color.array as Float32Array, 0);
		ringGeometry.attributes.color.needsUpdate = true;

		const blending = light ? NormalBlending : AdditiveBlending;
		for (const material of [nodeMaterial, ringMaterial, edgeMaterial, focusMaterial]) {
			material.blending = blending;
			material.needsUpdate = true;
		}
		uniforms.uSolid.value = light ? 1 : 0;
		edgeBaseOpacity = light ? 0.3 : 0.26;
		refreshFocus();
	}
	const themeObserver = new MutationObserver(applyTheme);
	themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
	applyTheme();
	setLabelled(topNodes);

	// --- sizing ----------------------------------------------------------

	let width = 1;
	let height = 1;
	function resize() {
		width = host.clientWidth;
		height = host.clientHeight;
		const ratio = Math.min(devicePixelRatio, 2);
		renderer.setPixelRatio(ratio);
		renderer.setSize(width, height, false);
		uniforms.uPixelRatio.value = ratio;
		camera.aspect = width / height;
		const tangent = Math.tan((camera.fov * Math.PI) / 360);
		if (width >= 960) {
			// the graph sits in the right half, beside the headline
			camera.position.z = 330;
			world.position.set(Math.min(95, (camera.aspect - 1) * 95), 22, 0);
			restYaw = -0.2; // up and to the left of centre, clear of the console
			restPitch = -0.55;
		} else {
			// narrow screens: fit the graph to the width and park it behind the top of the hero
			camera.position.z = 250 / (2 * tangent * camera.aspect);
			const visibleHeight = 2 * tangent * camera.position.z;
			world.position.set(0, (0.5 - 190 / height) * visibleHeight, 0);
			restYaw = 0;
			restPitch = 0;
		}
		dustGroup.position.copy(world.position);
		uniforms.uDistance.value = camera.position.z;
		camera.updateProjectionMatrix();
	}
	const resizeObserver = new ResizeObserver(resize);
	resizeObserver.observe(host);
	resize();

	// --- pointer ---------------------------------------------------------

	canvas.addEventListener('pointerdown', (event) => {
		dragging = true;
		moved = 0;
		lastX = event.clientX;
		lastY = event.clientY;
		canvas.setPointerCapture(event.pointerId);
	});
	canvas.addEventListener('pointermove', (event) => {
		const bounds = canvas.getBoundingClientRect();
		pointer = { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
		if (!dragging) return;
		const dx = event.clientX - lastX;
		const dy = event.clientY - lastY;
		moved += Math.abs(dx) + Math.abs(dy);
		steering = false;
		spin = dx * 0.005;
		yaw += spin;
		pitch = Math.max(-1.1, Math.min(1.1, pitch + dy * 0.005));
		lastX = event.clientX;
		lastY = event.clientY;
	});
	canvas.addEventListener('pointerup', () => {
		if (dragging && moved < 5 && hovered !== -1) {
			for (const listener of pickListeners) listener(hovered);
		}
		dragging = false;
	});
	canvas.addEventListener('pointercancel', () => (dragging = false));
	canvas.addEventListener('pointerleave', () => (pointer = null));

	// the whole hero steers a gentle parallax, not only the canvas
	const onHeroMove = (event: PointerEvent) => {
		if (event.pointerType === 'touch') return;
		const bounds = hero.getBoundingClientRect();
		pointerX = ((event.clientX - bounds.left) / bounds.width - 0.5) * 2;
		pointerY = ((event.clientY - bounds.top) / bounds.height - 0.5) * 2;
	};
	if (!reduceMotion) hero.addEventListener('pointermove', onHeroMove);

	const projected = new Vector3();
	function screenOf(index: number) {
		projected.fromArray(positions, index * 3).applyMatrix4(world.matrixWorld).project(camera);
		return { x: (projected.x * 0.5 + 0.5) * width, y: (-projected.y * 0.5 + 0.5) * height, z: projected.z };
	}

	function setHovered(index: number) {
		if (index === hovered) return;
		hovered = index;
		canvas.style.cursor = index === -1 ? 'grab' : 'pointer';
		refreshLit();
		if (selected === -1) refreshFocus();
		if (index === -1) {
			tooltip.hidden = true;
			return;
		}
		const node = nodes[index];
		tooltip.querySelector('[data-name]')!.textContent = node.name;
		tooltip.querySelector('[data-kind]')!.textContent = node.kind;
		tooltip.querySelector('[data-loc]')!.textContent = `${node.path}:${node.line}`;
		tooltip.querySelector('[data-inbound]')!.textContent =
			`${node.refs} resolved reference${node.refs === 1 ? '' : 's'} · click to inspect`;
		tooltip.hidden = false;
	}

	// --- frame loop ------------------------------------------------------

	let visible = true;
	const visibility = new IntersectionObserver(([entry]) => (visible = entry.isIntersecting));
	visibility.observe(host);

	let started = 0;
	let previous = 0;
	let frame = 0;
	let builtReported = false;
	function tick(now: number) {
		frame = requestAnimationFrame(tick);
		if (!started) {
			started = now;
			previous = now;
		}
		if (!visible || document.hidden) {
			previous = now;
			return;
		}
		const delta = Math.min((now - previous) / 1000, 0.05);
		previous = now;
		const elapsed = (now - started) / 1000;
		uniforms.uTime.value = elapsed;

		// the graph assembles itself file by file, like an index being built
		const build = reduceMotion ? 1 : Math.min(elapsed / BUILD_SECONDS, 1);
		if (!reduceMotion) uniforms.uBuild.value = build < 1 ? build : 2;
		if (!builtReported) {
			for (const listener of buildListeners) listener(build);
			if (build >= 1) builtReported = true;
		}
		const edgesIn = reduceMotion ? 1 : Math.max(0, Math.min((elapsed - BUILD_SECONDS * 0.45) / 1.6, 1));
		uniforms.uDim.value += (dimTarget - uniforms.uDim.value) * Math.min(delta * 7, 1);
		edgeMaterial.opacity = edgeBaseOpacity * edgesIn * (1 - uniforms.uDim.value * 0.5);
		focusMaterial.opacity = 0.95 * edgesIn;

		// rotation: idle spin, drag inertia, or easing toward the selected node
		if (!dragging) {
			if (steering) {
				spin *= 0.9;
			} else {
				const idle = reduceMotion ? 0 : hovered === -1 ? 0.003 : 0.0006;
				spin += (idle - spin) * 0.03;
				yaw += spin * (delta * 60);
				pitch += (0.12 - pitch) * 0.004;
			}
		}
		parallaxX += (pointerX - parallaxX) * 0.05;
		parallaxY += (pointerY - parallaxY) * 0.05;
		const sway = steering && !reduceMotion ? Math.sin(elapsed * 0.6) * 0.07 : 0;
		const ease = Math.min(delta * (steering ? 3.2 : 12), 1);
		world.rotation.y += (yaw + sway + parallaxX * 0.16 - world.rotation.y) * ease;
		world.rotation.x += (pitch + parallaxY * 0.1 - world.rotation.x) * ease;
		dustGroup.rotation.y = world.rotation.y * 0.35;
		dustGroup.rotation.x = world.rotation.x * 0.35;

		// scrolling away pushes into the graph and fades it
		const scrolled = Math.max(0, Math.min(window.scrollY / Math.max(hero.offsetHeight, 1), 1));
		world.scale.setScalar(1 + scrolled * 0.45);
		canvas.style.opacity = String(1 - scrolled * 0.85);
		world.updateMatrixWorld();

		if (!reduceMotion) {
			pulsePoints.visible = edgesIn > 0.3;
			const focusEdges = selected !== -1 ? adjacency[selected] : null;
			pulses.forEach((pulse, index) => {
				pulse.t += pulse.speed * delta * (focusEdges ? 1.5 : 1);
				if (pulse.t >= 1) {
					pulse.t = 0;
					pulse.edge = focusEdges?.length
						? focusEdges[(index * 7 + Math.floor(elapsed * 3)) % focusEdges.length]
						: (pulse.edge * 31 + 17 + index) % edges.length;
				}
				const [source, target, , confidence] = edges[pulse.edge];
				for (let axis = 0; axis < 3; axis += 1) {
					const from = positions[source * 3 + axis];
					pulsePositions[index * 3 + axis] = from + (positions[target * 3 + axis] - from) * pulse.t;
				}
				edgePalette[confidence].toArray(pulseColors, index * 3);
			});
			pulseGeometry.attributes.position.needsUpdate = true;
			pulseGeometry.attributes.color.needsUpdate = true;
		}

		if (pointer && !dragging) {
			let best = -1;
			let bestDistance = 18;
			for (let index = 0; index < count; index += 1) {
				const at = screenOf(index);
				if (at.z > 1) continue;
				const distance = Math.hypot(at.x - pointer.x, at.y - pointer.y);
				if (distance < bestDistance) {
					bestDistance = distance;
					best = index;
				}
			}
			setHovered(best);
		} else if (!pointer) {
			setHovered(-1);
		}
		if (hovered !== -1) {
			const at = screenOf(hovered);
			const flip = at.x > width - 300;
			tooltip.style.transform = `translate(${Math.round(at.x + (flip ? -16 : 16))}px, ${Math.round(at.y - 14)}px) translateX(${flip ? '-100%' : '0'})`;
		}

		labels.forEach((label, slot) => {
			const index = labelled[slot];
			if (index === undefined) {
				label.style.opacity = '0';
				return;
			}
			const at = screenOf(index);
			const depth = Math.max(0, Math.min(1, (0.985 - at.z) * 60));
			const strong = index === selected;
			label.style.transform = `translate(${Math.round(at.x + 12)}px, ${Math.round(at.y - 9)}px)`;
			label.style.opacity = String(Math.min(build * 1.4, 1) * (strong ? 1 : 0.3 + depth * 0.7) * (1 - scrolled));
		});

		renderer.render(scene, camera);
	}
	frame = requestAnimationFrame(tick);
	host.classList.add('live');

	return {
		select,
		highlight,
		onPick: (listener) => pickListeners.push(listener),
		onBuild: (listener) => buildListeners.push(listener),
		destroy() {
			cancelAnimationFrame(frame);
			themeObserver.disconnect();
			resizeObserver.disconnect();
			visibility.disconnect();
			hero.removeEventListener('pointermove', onHeroMove);
			renderer.dispose();
		},
	};
}
