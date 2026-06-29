import requests
import re
from typing import Dict, Any, Optional


class GrafanaTools:
    def __init__(self, url: str, api_key: str):
        self.url = url
        self.api_key = api_key

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def create_dashboard(
        self, dashboard_name: str, promql: str, panel_type: str = "timeseries"
    ) -> str:
        url = f"{self.url}/api/dashboards/db"
        cleaned_promql = re.sub(
            r"\[[0-9]+[smhdwy](:[0-9]+[smhdwy])?\]$", "", promql.strip()
        )
        uid = dashboard_name.replace(" ", "_").lower()

        target_json = {"expr": cleaned_promql, "legendFormat": "{{instance}}"}
        if panel_type == "gauge":
            target_json["instant"] = True

        panel_config = {
            "title": dashboard_name,
            "type": panel_type,
            "gridPos": {"x": 0, "y": 0, "w": 24, "h": 8},
            "targets": [target_json],
        }

        if panel_type == "gauge":
            panel_config["options"] = {
                "reduceOptions": {"values": True, "calcs": ["last"]}
            }

        payload = {
            "dashboard": {
                "id": None,
                "uid": uid,
                "title": dashboard_name,
                "panels": [panel_config],
                "schemaVersion": 36,
                "version": 1,
            },
            "overwrite": True,
        }

        resp = requests.post(url, json=payload, headers=self._headers())
        if resp.status_code != 200:
            return f"Grafana Error {resp.status_code}: {resp.text}"

        return f"Dashboard '{dashboard_name}' created with PromQL: {promql}"

    def get_dashboard_uid(self, dashboard_name: str) -> str:
        try:
            url = f"{self.url}/api/search?query={dashboard_name}&type=dash-db"
            resp = requests.get(url, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()

            if not data:
                return f"No dashboard found with name '{dashboard_name}'"

            uid = data[0].get("uid")
            title = data[0].get("title")
            return f"Dashboard found: {title}, UID: {uid}"
        except Exception as e:
            return f"Error fetching dashboard UID: {str(e)}"

    def update_dashboard(self, dashboard_uid: str, new_title: str, promql: str) -> str:
        get_url = f"{self.url}/api/dashboards/uid/{dashboard_uid}"
        try:
            resp = requests.get(get_url, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            dashboard = data.get("dashboard")
            if not dashboard:
                return "Dashboard JSON malformed."

            dashboard["title"] = new_title
            panels = dashboard.get("panels", [])
            new_panel = {
                "id": len(panels) + 1,
                "title": f"New: {new_title}",
                "type": "timeseries",
                "gridPos": {"x": 0, "y": 8 * len(panels), "w": 24, "h": 8},
                "targets": [{"expr": promql, "legendFormat": "{{instance}}"}],
            }
            panels.append(new_panel)
            dashboard["panels"] = panels

            update_url = f"{self.url}/api/dashboards/db"
            update_resp = requests.post(
                update_url,
                json={"dashboard": dashboard, "overwrite": True},
                headers=self._headers(),
            )
            update_resp.raise_for_status()
            return f"Dashboard '{new_title}' updated!"
        except Exception as e:
            return f"Error updating dashboard: {str(e)}"
