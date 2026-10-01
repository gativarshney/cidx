const escapeHtml = (text: string) =>
	text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/**
 * Colour captured cidx output for display. The text is never changed, only
 * wrapped: confidence tags, path:line locations, symbol kinds, and the
 * metadata trailer each get a class.
 */
export function tint(output: string): string {
	return escapeHtml(output)
		.replace(/\[(exact|import|name-only)\]/g, '<span class="t-$1">[$1]</span>')
		.replace(/([\w./-]+\.(?:py|pyi|tsx?|jsx?|md|yaml)):(\d+)/g, '<span class="t-loc">$1:$2</span>')
		.replace(/ {2}(function|class|method|const|import) {2}/g, '  <span class="t-kind">$1</span>  ')
		.replace(/^(truncated: true, total_matches: \d+|index_age_ms: \d+)$/gm, '<span class="t-meta">$1</span>')
		.replace(/^(no drift: .*)$/gm, '<span class="t-ok">$1</span>')
		.replace(/^(cidx: .*)$/gm, '<span class="t-meta">$1</span>');
}

export const formatNumber = (value: number) => value.toLocaleString('en-US');
