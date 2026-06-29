export type AttachmentRef = {
  relative_path: string;
  original_name?: string | null;
  mime?: string | null;
  original_relative_path?: string | null;
};

/** Same merge as Chainlit `_merge_attachment_refs`. */
export function mergeAttachmentRefs(newFromMessage: AttachmentRef[], existingOnServer: AttachmentRef[]): AttachmentRef[] {
  const seen = new Set<string>();
  const merged: AttachmentRef[] = [];
  for (const a of newFromMessage) {
    const rp = a.relative_path;
    if (!rp || seen.has(rp)) continue;
    seen.add(rp);
    merged.push(a);
  }
  for (const a of existingOnServer) {
    const rp = a.relative_path;
    if (!rp || seen.has(rp)) continue;
    seen.add(rp);
    merged.push(a);
  }
  return merged;
}
