/**
 * Turn web-search citation markers [1], [2] into in-message anchor links
 * that match WebSourcesBar ids (`#source-{messageId}-{n}`).
 */

const CODE_FENCE_RE = /(```[\s\S]*?```|`[^`]+`)/g;
const PLAIN_CITATION_RE = /(^|[^\[])\[(\d{1,3})\](?!\(|\])/g;
const MARKDOWN_CITATION_RE = /\[(\d{1,3})\]\(https?:\/\/[^)]+\)/gi;
/** Model sometimes omits the opening bracket: "confidenza 18[29]" */
const GLUED_CITATION_RE = /(\s)(\d{1,3})(\[\d{1,3}\])/g;
const LINK_CLEANUP_RE = /\[\[?([^\]]+)\]\]?\(([^)]+)\)/g;

function citationAnchor(prefix: string, index: string): string {
  return `[${index}](#${prefix}-${index})`;
}

/**
 * Normalize citation markers outside fenced / inline code blocks.
 */
export function formatTextWithCitations(text: string, messageId?: string): string {
  if (!text) return text;
  const prefix = messageId ? `source-${messageId}` : "source";
  const parts = text.split(CODE_FENCE_RE);
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 !== 0) continue;
    let chunk = parts[i];
    // [1](https://…) → same anchor as plain [1] (model ignored web_research_protocol)
    chunk = chunk.replace(MARKDOWN_CITATION_RE, (_, n: string) => citationAnchor(prefix, n));
    // "text 18[29]" → "text [18][29]"
    chunk = chunk.replace(GLUED_CITATION_RE, (_, lead: string, n: string, rest: string) => {
      return `${lead}[${n}]${rest}`;
    });
    chunk = chunk.replace(
      PLAIN_CITATION_RE,
      (_, lead: string, n: string) => `${lead}${citationAnchor(prefix, n)}`,
    );
    chunk = chunk.replace(LINK_CLEANUP_RE, (match, label: string, url: string) => {
      const cleanUrl = url.trim().startsWith("#") ? url.trim() : url.trim().replace(/ /g, "%20");
      return `[${String(label).trim()}](${cleanUrl})`;
    });
    chunk = chunk.replace(/\\\[/g, "$$\n").replace(/\\\]/g, "\n$$");
    chunk = chunk.replace(/\\\(/g, "$").replace(/\\\)/g, "$");
    parts[i] = chunk;
  }
  return parts.join("");
}
