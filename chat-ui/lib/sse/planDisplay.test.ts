import { describe, expect, it } from "vitest";
import {
  isOrchestrationPlanEvent,
  isUnusablePlanMarkdown,
  normalizePlanPendingChunk,
  orchestrationPlanToMarkdown,
  planFromOrchestrationEvent,
  resolvePlanEditorMarkdown,
  type OrchestrationPlanPendingEvent,
} from "./planDisplay";

describe("planFromOrchestrationEvent", () => {
  it("returns structured plan from SSE payload", () => {
    const evt: OrchestrationPlanPendingEvent = {
      type: "orchestration_plan_pending",
      plan_id: "execution_plan_abc",
      plan: {
        goal: "Test goal",
        tasks: [{ id: "task_01", title: "First" }],
      },
      revision: 1,
    };
    expect(isOrchestrationPlanEvent(evt)).toBe(true);
    const plan = planFromOrchestrationEvent(evt);
    expect(plan?.goal).toBe("Test goal");
    expect(plan?.tasks[0]?.id).toBe("task_01");
  });

  it("builds markdown from structured plan without chat parse", () => {
    const md = orchestrationPlanToMarkdown({
      goal: "Ship feature",
      tasks: [{ id: "task_01", title: "Design", depends_on: [] }],
    });
    expect(md).toContain("## Goal");
    expect(md).toContain("`task_01`");
    expect(md).toContain("**Design**");
  });

  it("normalizes pending chunk with SSOT plan JSON", () => {
    const normalized = normalizePlanPendingChunk({
      type: "orchestration_plan_pending",
      plan_id: "p1",
      plan: { goal: "G", tasks: [{ id: "task_01", title: "T" }] },
    });
    expect(normalized.plan_markdown).toContain("task_01");
    expect(normalized.plan?.goal).toBe("G");
  });

  it("detects raw JSON task array as unusable markdown", () => {
    const raw = JSON.stringify([{ id: "task_01", title: "First", description: "Do it" }]);
    expect(isUnusablePlanMarkdown(raw)).toBe(true);
    const md = resolvePlanEditorMarkdown(raw, {
      goal: "G",
      tasks: [{ id: "task_01", title: "First", description: "Do it" }],
    });
    expect(md).toContain("`task_01`");
    expect(md).toContain("Description: Do it");
  });
});
