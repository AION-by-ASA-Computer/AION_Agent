/** Strip Qwen/vLLM artifacts that leak into text_delta when thinking/tools mis-route. */

const COMPLETE_BLOCK =
  /<(thinking|redacted_thinking|tool_code|tool_call)>[\s\S]*?<\/\1>/gi;
const LONE_TOOL_TAG = /<\/?(?:tool_code|tool_call)>/gi;

function splitPartialTagTail(text: string): { safe: string; pending: string } {
  const lastLt = text.lastIndexOf("<");
  if (lastLt !== -1 && !text.slice(lastLt).includes(">")) {
    return { safe: text.slice(0, lastLt), pending: text.slice(lastLt) };
  }
  return { safe: text, pending: "" };
}

export class StreamSanitizer {
  private pending = "";

  filter(delta: string): string {
    if (!delta) return "";
    this.pending += delta;
    let text = this.pending.replace(COMPLETE_BLOCK, "").replace(LONE_TOOL_TAG, "");

    const { safe, pending } = splitPartialTagTail(text);
    this.pending = pending;
    if (!safe.trim()) return "";
    return safe;
  }

  flush(): string {
    const rest = this.pending.replace(COMPLETE_BLOCK, "").replace(LONE_TOOL_TAG, "");
    this.pending = "";
    return rest.trim() ? rest : "";
  }
}
