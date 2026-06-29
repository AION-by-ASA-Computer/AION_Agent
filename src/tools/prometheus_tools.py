import requests
import time
import re
import pandas as pd
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class ChartData:
    query: str
    dataframe: pd.DataFrame
    range_seconds: int
    step_seconds: int
    chart_kind: str = "line"
    x_key: str = "index"
    series_keys: Optional[List[str]] = None
    stacked: bool = False
    y_label: Optional[str] = None
    legend_off: bool = False

class PrometheusTools:
    def __init__(self, api_url: str, timeout: int = 10):
        self.api_url = api_url
        self.timeout = timeout

    def search_metric(self, metric_name: str) -> str:
        try:
            url = f"{self.api_url}/label/__name__/values"
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("status") == "success":
                all_metrics = data.get("data", [])
                matched = [m for m in all_metrics if metric_name.lower() in m.lower()]
                
                if not matched:
                    return f"No metrics found matching '{metric_name}'"
                
                if len(matched) > 50:
                    return f"Found {len(matched)} metrics (showing first 50):\n" + "\n".join(matched[:50])
                
                return f"Found {len(matched)} metric(s):\n" + "\n".join(matched)
            return "Error querying Prometheus"
        except Exception as e:
            return f"Error searching metrics: {str(e)}"

    def get_metric_labels(self, metric_name: str, limit: int = 20) -> str:
        try:
            url = f"{self.api_url}/series"
            params = {"match[]": metric_name}
            resp = requests.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("status") != "success":
                return f"Error: {data.get('error', 'Unknown error')}"
            
            series = data.get("data", [])
            if not series:
                return f"No series found for metric '{metric_name}'"
            
            result = f"Found {len(series)} series for '{metric_name}':\n\n"
            for i, s in enumerate(series[:limit]):
                labels = s.copy()
                labels.pop("__name__", None)
                label_str = ", ".join([f'{k}="{v}"' for k, v in sorted(labels.items())])
                result += f"{i+1}. {{{label_str}}}\n"
            
            if len(series) > limit:
                result += f"\n... and {len(series) - limit} more series"
            
            all_label_keys = set()
            for s in series:
                all_label_keys.update(s.keys())
            all_label_keys.discard("__name__")
            result += f"\n\nAvailable labels: {', '.join(sorted(all_label_keys))}"
            return result
        except Exception as e:
            return f"Error getting metric labels: {str(e)}"

    def execute_promql(self, query: str) -> str:
        try:
            url = f"{self.api_url}/query"
            params = {"query": query}
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "success":
                return f"Error executing query: {data.get('error', 'Unknown error')}"
            
            result_type = data.get("data", {}).get("resultType", "vector")
            result_data = data.get("data", {}).get("result", [])
            
            if not result_data:
                return "No data returned for this query."
                
            if result_type == "vector":
                return self._format_vector_result(result_data)
            elif result_type == "matrix":
                return self._format_matrix_stats(result_data)
            return f"Unsupported result type: {result_type}"
        except Exception as e:
            return f"Error executing PromQL: {str(e)}"

    def get_chart_data(self, query: str) -> Optional[ChartData]:
        """Core logic to fetch data for charts. Returns pure data, no UI."""
        range_seconds = 24 * 3600
        step_seconds = 60
        cleaned_query = query.strip()
        
        match = re.search(r'\[([0-9]+[smhdwy])(:([0-9]+[smhdwy]))?\]$', cleaned_query)
        if match:
            range_seconds = self._parse_duration(match.group(1))
            if match.group(3):
                step_seconds = self._parse_duration(match.group(3))
            cleaned_query = cleaned_query[:match.start()].strip()
            
        end_ts = int(time.time())
        start_ts = end_ts - range_seconds

        url = f"{self.api_url}/query_range"
        params = {"query": cleaned_query, "start": start_ts, "end": end_ts, "step": step_seconds}
        
        response = requests.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") != "success" or not data.get("data", {}).get("result"):
            return None

        result_data = data["data"]["result"]
        all_series = {}
        for item in result_data:
            label_str = self._extract_label_string(item.get("metric", {}))
            values = item.get("values", [])
            if not values: continue
            
            timestamps = [float(v[0]) for v in values]
            metric_values = [float(v[1]) for v in values]
            
            time_index = pd.to_datetime(timestamps, unit='s', utc=True).tz_convert('Europe/Rome')
            all_series[label_str] = pd.Series(data=metric_values, index=time_index)

        if not all_series: return None
        
        df = pd.DataFrame(all_series)
        MAX_POINTS = 300
        if len(df) > MAX_POINTS:
            df = df.iloc[::len(df) // MAX_POINTS]
            
        return ChartData(query=query, dataframe=df, range_seconds=range_seconds, step_seconds=step_seconds)

    def _extract_label_string(self, labels: Dict[str, str]) -> str:
        relevant_keys = ["instance", "job", "device", "gpu", "mode", "mountpoint", "name"]
        parts = [labels[k] for k in relevant_keys if k in labels and labels[k]]
        if not parts:
            parts = [f"{k}={v}" for k, v in list(labels.items())[:2]]
        return " - ".join(parts) if parts else "Value"

    def _parse_duration(self, duration_str: str) -> int:
        if not duration_str: return 0
        val = int(duration_str[:-1])
        units = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800, 'y': 31536000}
        return val * units.get(duration_str[-1], 1)

    def _format_vector_result(self, result_data: list) -> str:
        output_lines = []
        for item in result_data:
            labels = {k: v for k, v in item.get("metric", {}).items() if k != "__name__"}
            label_str = ", ".join([f'{k}="{v}"' for k, v in labels.items()])
            val = item.get("value", ["", "N/A"])[1]
            output_lines.append(f"{{{label_str}}} => {val}")
        return "\n".join(output_lines[:20]) + (f"\n... ({len(output_lines)-20} more)" if len(output_lines) > 20 else "")

    def _format_matrix_stats(self, result_data: list) -> str:
        stats_lines = []
        for item in result_data:
            metric_values = [float(v[1]) for v in item.get("values", [])]
            if metric_values:
                label_str = self._extract_label_string(item.get("metric", {}))
                stats_lines.append(f"- {label_str}: Curr={metric_values[-1]:.2f}, Avg={sum(metric_values)/len(metric_values):.2f}")
        return "Summary stats:\n" + "\n".join(stats_lines)
