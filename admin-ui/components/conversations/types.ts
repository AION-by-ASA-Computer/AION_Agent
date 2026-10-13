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
