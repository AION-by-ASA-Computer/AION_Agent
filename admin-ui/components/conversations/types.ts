export type Conversation = {
  id: string;
  tenant_id: string;
  user_id: string;
  profile_slug: string;
  title: string | null;
  message_count: number;
  updated_at: string | number;
  disliked_count?: number;
  liked_count?: number;
  comment_count?: number;
  error_count?: number;
  /** Set on side threads: the conversation the thread was opened from. */
  parent_conversation_id?: string | null;
  /** Assistant message of the parent the highlighted passage belongs to. */
  parent_message_id?: string | null;
  /** The highlighted passage the thread was opened on. */
  anchor_quote?: string | null;
};

/** A top-level conversation with its side threads (newest first). */
export type ConversationFamily = {
  root: Conversation;
  threads: Conversation[];
  /** True when the parent row is missing and a thread stands in as the root. */
  orphan?: boolean;
};

export type ThreadStep = {
  id: string;
  name: string;
  input?: string | null;
  output?: string | null;
  is_error?: boolean;
};

export type ThreadArtifact = {
  id: string;
  kind?: string | null;
  mime?: string | null;
  original_name?: string | null;
  storage_key?: string | null;
  size_bytes?: number | null;
  content?: string | null;
};

export type ThreadMessage = {
  id: string;
  seq: number;
  role: string;
  content?: string | null;
  reasoning?: string | null;
  tool_name?: string | null;
  created_at?: string | number | null;
  steps?: ThreadStep[];
  artifacts?: ThreadArtifact[];
  rating?: number | null;
  feedback_comment?: string | null;
};

/** A thread message the admin should look at: a thumbs-down or a failed tool call. */
export const isFlagged = (m: ThreadMessage) => m.rating === -1 || !!m.steps?.some((s) => s.is_error);

export const needsAttention = (c: Conversation) => (c.disliked_count ?? 0) + (c.error_count ?? 0) > 0;
