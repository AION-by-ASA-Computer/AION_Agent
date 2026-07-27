import { describe, expect, it } from "vitest";
import {
  mapPiEventToAion,
  toolResultLooksLikeError,
  toolResultToText,
} from "../src/event-mapper.js";

describe("mapPiEventToAion", () => {
  it("maps text deltas to token chunks", () => {
    const chunks = mapPiEventToAion({
      type: "message_update",
      assistantMessageEvent: { type: "text_delta", delta: "hi" },
    } as never);
    expect(chunks).toEqual([{ type: "token", content: "hi" }]);
  });

  it("maps tool execution lifecycle", () => {
    const start = mapPiEventToAion({
      type: "tool_execution_start",
      toolCallId: "c1",
      toolName: "web_search",
      args: { query: "test" },
    } as never);
    expect(start[0]).toMatchObject({
      type: "tool_event",
      event: { type: "tool_start", name: "web_search" },
    });
  });

  it("extracts text from AgentToolResult content blocks", () => {
    expect(
      toolResultToText({
        content: [{ type: "text", text: '{"results":[]}' }],
        isError: false,
      }),
    ).toBe('{"results":[]}');
  });

  it("maps tool_execution_end with structured result", () => {
    const end = mapPiEventToAion({
      type: "tool_execution_end",
      toolCallId: "c1",
      toolName: "skill_view",
      result: {
        content: [{ type: "text", text: "# Skill body" }],
        isError: false,
      },
      isError: false,
    } as never);
    expect(end[0]).toMatchObject({
      type: "tool_event",
      event: {
        type: "tool_end",
        name: "skill_view",
        output: "# Skill body",
      },
    });
  });

  it("maps tool_execution_end errors to tool_error", () => {
    const end = mapPiEventToAion({
      type: "tool_execution_end",
      toolCallId: "c2",
      toolName: "sandbox_run_python_file",
      result: {
        content: [{ type: "text", text: "No MCP server" }],
        isError: true,
      },
      isError: true,
    } as never);
    expect(end[0]).toMatchObject({
      type: "tool_event",
      event: {
        type: "tool_error",
        name: "sandbox_run_python_file",
        error: "No MCP server",
      },
    });
  });

  it("maps ok:false JSON tool results to tool_error even when isError is false", () => {
    const payload = JSON.stringify({
      ok: false,
      error: "missing_arguments",
      message: "missing content",
    });
    const end = mapPiEventToAion({
      type: "tool_execution_end",
      toolCallId: "c3",
      toolName: "sandbox_write_workspace_file",
      result: {
        content: [{ type: "text", text: payload }],
        isError: false,
      },
      isError: false,
    } as never);
    expect(end[0]).toMatchObject({
      type: "tool_event",
      event: {
        type: "tool_error",
        name: "sandbox_write_workspace_file",
        error: payload,
      },
    });
  });

  it("detects structured tool errors in plain text", () => {
    expect(
      toolResultLooksLikeError(
        JSON.stringify({ ok: false, error: "tool_args_truncated" }),
      ),
    ).toBe(true);
    expect(toolResultLooksLikeError('{"ok": true}')).toBe(false);
  });
});
