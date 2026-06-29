---
name: charts_generation
description: Guideline for generating interactive dynamic charts (line, area, bar) using the charts render_chart MCP tool instead of writing custom static HTML pages.
tags: [charts, visualization, recharts, reporting]
status: verified
source: curated
version: 1
---

# Interactive Dynamic Charts (render_chart MCP)

This skill guides you on how to dynamically generate interactive, native charts (Line, Area, Bar) directly in the user's Chat Workspace using the `charts` MCP `render_chart` tool. 

---

## When to use render_chart

Always prefer `render_chart` over writing custom static `.html` files in the workspace (like using `sandbox_write_workspace_file`) when the user asks for a visualization (e.g. data distributions, performance metrics, task stats, database reports). 

Emitting a native chart inside `chat-ui` via the `render_chart` tool provides an outstanding, premium, fully integrated user experience with interactive tooltips, custom grids, and smooth animations.

---

## How to call the tool

The `render_chart` tool under the `charts` server has the following signature:
```python
def render_chart(
    query: str,
    data: Optional[List[Dict[str, Any]]] = None,
    chart_kind: str = "line",
    x_key: str = "index",
    series_keys: Optional[List[str]] = None,
    stacked: bool = False,
    legend_off: bool = False,
    y_label: str = "",
)
```

### 1. Drawing Arbitrary Inline Data (ClickUp, SQL DB, Analyzed Logs)
To display custom, arbitrary data you have collected or analyzed:
- Pass a descriptive name/title to `query`.
- Format the data as a list of flat dictionaries under the `data` parameter.
- Set `chart_kind` to `"line"`, `"area"`, or `"bar"`.
- Set `x_key` to the category/X-axis label column (default is `"index"`).
- Set layout features like `stacked`, `legend_off`, or `y_label` where relevant.

**Example 1: Task Distribution by Developer (Bar Chart)**
```python
render_chart(
    query="Task Distribution by Team Member",
    data=[
        {"index": "JustBeGiusee_", "Tasks": 11},
        {"index": "Luca D'Agostaro", "Tasks": 4},
        {"index": "Alessio Colombo", "Tasks": 1},
        {"index": "Unassigned", "Tasks": 1}
    ],
    chart_kind="bar",
    x_key="index",
    series_keys=["Tasks"],
    y_label="Number of Tasks"
)
```

**Example 2: Stacked Area Chart (Volume over Time)**
```python
render_chart(
    query="User Sessions Activity",
    data=[
        {"index": "10:00", "mobile": 12, "web": 30},
        {"index": "11:00", "mobile": 18, "web": 45},
        {"index": "12:00", "mobile": 25, "web": 50}
    ],
    chart_kind="area",
    x_key="index",
    series_keys=["mobile", "web"],
    stacked=True,
    y_label="Active Users"
)
```

### 2. Backwards-Compatible Prometheus Queries (PromQL Mode)
If `data` is omitted, and the Prometheus server is running, `render_chart` will automatically execute `query` as a PromQL time-range query and fetch the metrics.
- Pass the raw PromQL query (e.g. `rate(http_requests_total[5m])`) to `query`.
- Leave `data` empty.
- Specify the `chart_kind` ("line", "area", or "bar").

---

## Avoid common mistakes

- **Do NOT prepend `workspace/`** to files or use `sandbox_write_workspace_file` for visualizations when the user expects to see the chart in the chat.
- **Always keep keys consistent** in the `data` list of dictionaries. The keys of the first row dictionary dictate the schema.
- **Ensure `x_key` actually exists** in every record inside the `data` array.
