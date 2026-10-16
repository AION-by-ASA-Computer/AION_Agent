export interface ProfileItem {
  name: string;
  slug?: string;
  description?: string;
}

export interface UserItem {
  id: string;
  tenant_id?: string;
  identifier?: string;
  display_name?: string;
}

export interface ToolMetricSummary {
  tool_name: string;
  mcp_server: string;
  call_count: number;
  error_count: number;
  success_rate: number;
  avg_duration_seconds: number;
}

export interface LastTurnToolCall {
  tool_name: string;
  mcp_server: string;
  status: string;
  count: number;
}

export interface TimeSeriesDataPoint {
  timestamp: string;
  value: number;
}

export interface ProfileMetricSummary {
  profile: string;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  reasoning_tokens: number;
  total_turns: number;
  total_tool_calls: number;
  tool_success_rate: number;
  avg_turn_duration_seconds: number;
}

export interface UserToolCallSummary {
  tool_name: string;
  mcp_server: string;
  call_count: number;
  error_count: number;
}

export interface UserProfileUsageSummary {
  profile: string;
  total_turns: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  reasoning_tokens?: number;
  total_tokens: number;
  total_tool_calls: number;
  usage_frequency_percent: number;
  tools_breakdown?: UserToolCallSummary[];
}

export interface UserMetricSummary {
  user_id: string;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  reasoning_tokens: number;
  total_turns: number;
  total_tool_calls: number;
  tool_success_rate: number;
  avg_turn_duration_seconds: number;
  profile_breakdown: UserProfileUsageSummary[];
}

export interface MCPCallError {
  timestamp?: string;
  tool_name: string;
  mcp_server: string;
  profile: string;
  status: string;
  error_count: number;
  error_message?: string;
}

export interface MetricsOverviewData {
  prometheus_connected: boolean;
  prometheus_url: string;
  profile?: string;
  user_id?: string;
  time_range: string;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  reasoning_tokens: number;
  last_turn_prompt_tokens: number;
  last_turn_completion_tokens: number;
  last_turn_reasoning_tokens: number;
  total_turns: number;
  avg_turn_duration_seconds: number;
  p95_turn_duration_seconds: number;
  last_turn_duration_seconds: number;
  total_tool_calls: number;
  tool_success_rate: number;
  total_failures: number;
  failure_breakdown: Record<string, number>;
  tool_metrics: ToolMetricSummary[];
  last_turn_tool_calls: LastTurnToolCall[];
  last_turn_tools_by_profile: Record<string, LastTurnToolCall[]>;
  profile_metrics: ProfileMetricSummary[];
  user_metrics?: UserMetricSummary[];
  mcp_call_errors: MCPCallError[];
  token_usage_by_model: Record<string, Record<string, number>>;
  tokens_series?: TimeSeriesDataPoint[];
  turn_duration_series?: TimeSeriesDataPoint[];
  turns_series?: TimeSeriesDataPoint[];
  tool_calls_series?: TimeSeriesDataPoint[];
}

export const TIME_RANGES = ["1h", "6h", "24h", "7d", "30d", "all"] as const;
export type TimeRange = (typeof TIME_RANGES)[number];

export type T = (key: string, vars?: Record<string, string | number>) => string;
