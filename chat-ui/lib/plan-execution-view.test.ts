import { describe, expect, it } from "vitest";
import {
  activitiesForPlanTask,
  findPlanTask,
  isMessageInPlanTask,
  isPlanTaskRunning,
  messageIdsForPlanTask,
  planExecutionProgressPercent,
  planTaskTurns,
  resolveCurrentPlanTask,
  taskHasConversation,
} from "./plan-execution-view";

describe("plan-execution-view", () => {
  it("messageIdsForPlanTask collects user and assistant ids", () => {
    const ids = messageIdsForPlanTask({
      task_id: "task_01",
      user_message_id: "u1",
      assistant_message_id: "a1",
    });
    expect(ids.has("u1")).toBe(true);
    expect(ids.has("a1")).toBe(true);
  });

  it("messageIdsForPlanTask includes all turns when present", () => {
    const ids = messageIdsForPlanTask({
      task_id: "task_01",
      turns: [
        { user_message_id: "u1", assistant_message_id: "a1" },
        { user_message_id: "u2", assistant_message_id: "a2" },
      ],
    });
    expect(ids.size).toBe(4);
    expect(ids.has("u2")).toBe(true);
    expect(ids.has("a2")).toBe(true);
  });

  it("planTaskTurns falls back to legacy id pair", () => {
    expect(
      planTaskTurns({
        task_id: "task_01",
        user_message_id: "u1",
        assistant_message_id: "a1",
      }),
    ).toEqual([{ user_message_id: "u1", assistant_message_id: "a1" }]);
  });

  it("isMessageInPlanTask matches either turn message", () => {
    const task = {
      task_id: "task_01",
      user_message_id: "u1",
      assistant_message_id: "a1",
    };
    expect(isMessageInPlanTask({ id: "u1", role: "internal" }, task)).toBe(true);
    expect(isMessageInPlanTask({ id: "a1", role: "assistant" }, task)).toBe(true);
    expect(isMessageInPlanTask({ id: "other", role: "user" }, task)).toBe(false);
  });

  it("isMessageInPlanTask matches metadata plan_task_id", () => {
    const task = { task_id: "task_02", user_message_id: "u9", assistant_message_id: "a9" };
    expect(
      isMessageInPlanTask(
        { id: "x1", role: "assistant", metadata: { plan_task_id: "task_02" } },
        task,
      ),
    ).toBe(true);
  });

  it("findPlanTask resolves by task_id", () => {
    const tasks = [
      { task_id: "task_01", title: "One" },
      { task_id: "task_02", title: "Two" },
    ];
    expect(findPlanTask(tasks, "task_02")?.title).toBe("Two");
    expect(findPlanTask(tasks, "missing")).toBeNull();
  });

  it("resolveCurrentPlanTask prefers running phase task", () => {
    const tasks = [
      { task_id: "task_01", status: "done" },
      { task_id: "task_02", status: "running" },
    ];
    expect(
      resolveCurrentPlanTask(tasks, { phase: "task_start", task_id: "task_02" })?.task_id,
    ).toBe("task_02");
  });

  it("planExecutionProgressPercent counts done tasks", () => {
    expect(
      planExecutionProgressPercent([
        { task_id: "a", status: "done" },
        { task_id: "b", status: "running" },
      ]),
    ).toBe(50);
  });

  it("taskHasConversation matches persisted metadata without turn ids", () => {
    const task = { task_id: "task_02" };
    expect(taskHasConversation(task)).toBe(false);
    expect(
      taskHasConversation(task, [
        { id: "a1", role: "assistant", metadata: { plan_task_id: "task_02" } },
      ]),
    ).toBe(true);
  });

  it("activitiesForPlanTask filters by task_id", () => {
    const acts = [
      { phase: "task_start", task_id: "task_01", label: "start 1" },
      { phase: "tool", task_id: "task_02", label: "tool 2" },
      { phase: "tool", label: "global" },
    ];
    expect(activitiesForPlanTask(acts, "task_02").map((a) => a.label)).toEqual([
      "tool 2",
      "global",
    ]);
  });

  it("isPlanTaskRunning detects live tool phase", () => {
    const task = { task_id: "task_02", status: "pending" };
    expect(
      isPlanTaskRunning(task, { phase: "tool", task_id: "task_02" }, "running", false),
    ).toBe(true);
    expect(
      isPlanTaskRunning(task, { phase: "tool", task_id: "task_02" }, "done", true),
    ).toBe(false);
  });
});
