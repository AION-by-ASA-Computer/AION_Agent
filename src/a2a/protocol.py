"""Contratto dati orchestrazione / task graph (Pydantic v2)."""
from __future__ import annotations

import json
import uuid
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field, model_validator


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ExecutionTask(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(default="", max_length=16000)
    depends_on: List[str] = Field(default_factory=list)
    target_profile: Optional[str] = Field(default=None, max_length=256)
    status: TaskStatus = TaskStatus.PENDING

    @model_validator(mode="after")
    def _no_self_dep(self) -> ExecutionTask:
        if self.id in self.depends_on:
            raise ValueError("depends_on non può includere il proprio id")
        return self


class ExecutionPlan(BaseModel):
    goal: str = Field(min_length=1, max_length=8000)
    tasks: List[ExecutionTask] = Field(min_length=1, max_length=64)
    version: int = 1

    @model_validator(mode="after")
    def _graph_consistent(self) -> ExecutionPlan:
        ids = {t.id for t in self.tasks}
        if len(ids) != len(self.tasks):
            raise ValueError("id task duplicati")
        for t in self.tasks:
            missing = [d for d in t.depends_on if d not in ids]
            if missing:
                raise ValueError(f"depends_on sconosciuti per task {t.id}: {missing}")
        # cycle check (DFS)
        adj = {t.id: list(t.depends_on) for t in self.tasks}

        visiting: set[str] = set()
        visited: set[str] = set()

        def dfs(n: str) -> None:
            if n in visiting:
                raise ValueError("grafo delle dipendenze contiene un ciclo")
            if n in visited:
                return
            visiting.add(n)
            for m in adj.get(n, []):
                dfs(m)
            visiting.remove(n)
            visited.add(n)

        for tid in ids:
            dfs(tid)
        return self

    def model_dump_json_safe(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_goal_and_tasks(cls, goal: str, tasks: Any) -> ExecutionPlan:
        """Accetta ``tasks`` come lista di dict, JSON string, o None (un solo task)."""
        if tasks is None:
            return cls(goal=goal, tasks=[ExecutionTask(title="main", description=goal)])
        if isinstance(tasks, str):
            s = tasks.strip()
            if not s:
                return cls(goal=goal, tasks=[ExecutionTask(title="main", description=goal)])
            try:
                data = json.loads(s)
            except json.JSONDecodeError as e:
                # Se fallisce il JSON, proviamo a parsarlo come Markdown
                from src.a2a.plan_markdown import markdown_to_plan
                dummy_md = f"# Plan\n\n## Goal\n{goal}\n\n## Tasks\n{s}"
                try:
                    return markdown_to_plan(dummy_md)
                except Exception as md_err:
                    raise ValueError(f"tasks non è un JSON valido né Markdown valido: {md_err} (Original JSON error: {e})")
        else:
            data = tasks
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise ValueError("tasks deve essere lista, dict o JSON string")
        if len(data) == 0:
            return cls(goal=goal, tasks=[ExecutionTask(title="main", description=goal)])
        out_tasks: List[ExecutionTask] = []
        for i, row in enumerate(data):
            if not isinstance(row, dict):
                raise ValueError(f"task[{i}] deve essere un oggetto")
            out_tasks.append(ExecutionTask.model_validate(row))
        return cls(goal=goal, tasks=out_tasks)
