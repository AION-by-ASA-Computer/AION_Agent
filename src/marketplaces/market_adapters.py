import os
import re
import requests
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("aion.marketplaces")


def parse_github_owner_repo(item: Dict[str, Any]) -> Optional[tuple[str, str]]:
    """Ritorna (owner, repo) minuscolo da URL GitHub o id ``github:`` / ``glama:``."""
    url = (item.get("url") or "").strip()
    m = re.search(r"github\.com/([^/]+)/([^/?#]+)", url, re.I)
    if m:
        return m.group(1).lower(), m.group(2).lower().rstrip("/").removesuffix(".git")
    iid = (item.get("id") or "").strip()
    low = iid.lower()
    if low.startswith("github:") or low.startswith("glama:"):
        rest = iid.split(":", 1)[1]
        parts = rest.split("/")
        if len(parts) >= 2:
            return parts[0].lower(), parts[1].lower().removesuffix(".git")
    return None


def parse_github_url(url: str) -> Optional[tuple[str, str]]:
    """(owner, repo) da URL GitHub grezzo."""
    u = (url or "").strip()
    if not u:
        return None
    if u.lower().startswith("github:"):
        parts = u.split(":", 1)[-1].strip().split("/")
        if len(parts) >= 2:
            return parts[0].lower(), parts[1].lower().removesuffix(".git")
    m = re.search(r"github\.com/([^/]+)/([^/?#]+)", u, re.I)
    if m:
        return m.group(1).lower(), m.group(2).lower().rstrip("/").removesuffix(".git")
    return None


def build_github_market_item(
    url: str,
    *,
    display_name: Optional[str] = None,
    description: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Voce marketplace sintetica per clone git da URL (installazione manuale Hub)."""
    pair = parse_github_url(url)
    if not pair:
        return None
    owner, repo = pair
    gh_url = f"https://github.com/{owner}/{repo}"
    return {
        "id": f"github:{owner}/{repo}",
        "name": (display_name or repo).strip(),
        "source": "GitHub (URL)",
        "description": description or f"Repository GitHub {owner}/{repo}",
        "url": gh_url,
        "install_type": "git",
    }


def npx_invoke_args(item: Dict[str, Any]) -> List[str]:
    """
    Argomenti da passare a ``command: npx`` (senza il binario ``npx`` stesso).
    Usa ``npx_args`` se presente (lista di stringhe), altrimenti ``-y`` + pacchetto da ``id``/``npx_package``.
    """
    custom = item.get("npx_args")
    if isinstance(custom, list) and custom and all(isinstance(x, str) for x in custom):
        return list(custom)
    pkg = (item.get("npx_package") or "").strip()
    if not pkg:
        raw_id = (item.get("id") or "").strip()
        if raw_id.lower().startswith("npx:"):
            pkg = raw_id.split(":", 1)[1]
    if not pkg:
        return ["-y", (item.get("id") or "package").strip()]
    return ["-y", pkg]


class MarketplaceAdapter:
    """
    Base class for MCP marketplace adapters.
    """

    def search(self, query: str) -> List[Dict[str, Any]]:
        raise NotImplementedError()

    def get_install_info(self, mcp_id: str) -> Dict[str, Any]:
        raise NotImplementedError()


class GlamaAdapter(MarketplaceAdapter):
    """
    Adapter for Glama.ai MCP Registry.
    """

    API_URL = "https://glama.ai/api/mcp/v1/servers"

    def search(self, query: str) -> List[Dict[str, Any]]:
        try:
            # Glama has a public list of servers
            response = requests.get(self.API_URL, timeout=10)
            if response.status_code != 200:
                return []

            data = response.json()
            # If it's a list directly or in a 'servers' key
            servers = data.get("servers") if isinstance(data, dict) else data

            results = []
            for s in servers:
                name = s.get("name") or s.get("repo", "")
                if (
                    not query
                    or query.lower() in name.lower()
                    or query.lower() in (s.get("description") or "").lower()
                ):
                    results.append(
                        {
                            "id": f"glama:{s.get('owner')}/{s.get('repo')}",
                            "name": name,
                            "source": "Glama.ai",
                            "description": s.get("description"),
                            "url": f"https://github.com/{s.get('owner')}/{s.get('repo')}",
                            "install_type": "git",
                        }
                    )
            return results
        except Exception as e:
            logger.error(f"Glama search failed: {e}")
            return []


class OfficialRegistryAdapter(MarketplaceAdapter):
    """
    Adapter for the Official MCP Registry (registry.modelcontextprotocol.io).
    """

    API_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"

    def search(self, query: str) -> List[Dict[str, Any]]:
        try:
            print(f"[DEBUG MCP QUERY] {query}")
            # The official registry currently returns a list at /v0.1/servers
            response = requests.get(
                self.API_URL, params={"search": query} if query else {}, timeout=10
            )
            if response.status_code != 200:
                logger.error(
                    f"Official Registry error {response.status_code}: {response.text}"
                )
                return []

            data = response.json()
            if isinstance(data, dict) and "servers" in data:
                server_items = data["servers"]
            elif isinstance(data, list):
                server_items = data
            else:
                logger.error(
                    f"Official Registry returned unexpected format: {type(data)}"
                )
                return []

            print(
                f"[DEBUG OFFICIAL REGISTRY] {len(server_items)} risultati:", flush=True
            )

            results = []
            for s in server_items:
                print(f"[DEBUG OFFICIAL REGISTRY] {s}", flush=True)
                if not isinstance(s, dict):
                    continue
                srv = s.get("server") if isinstance(s.get("server"), dict) else s
                if srv.get("remotes"):
                    install_type = "remote"
                elif srv.get("packages"):
                    install_type = "binary"
                else:
                    install_type = "stdio"

                results.append(
                    {
                        "id": f"mcp:{srv.get('name')}",
                        "name": srv.get("name"),
                        "source": "Official Registry",
                        "description": srv.get("description"),
                        "url": srv.get("websiteUrl"),
                        "install_type": install_type,
                        "remotes": srv.get("remotes"),
                        "_meta": s.get("_meta") if isinstance(s, dict) else {},
                    }
                )

            print(f"[DEBUG OFFICIAL REGISTRY] {len(results)} risultati:", flush=True)
            for r in results:
                print(f"  -> {r}", flush=True)

            return results
        except Exception as e:
            logger.error(f"Official Registry search failed: {e}")
            return []


class GoogleCloudAdapter(MarketplaceAdapter):
    """
    Adapter for official Google Cloud MCP servers.
    """

    def search(self, query: str) -> List[Dict[str, Any]]:
        # Focused on verified Google tools
        tools = [
            {
                "id": "google:mcp-toolbox",
                "name": "MCP Toolbox for Databases",
                "source": "Google Cloud",
                "description": "Securely connect AI agents to AlloyDB, Cloud SQL, Spanner, BigQuery, etc.",
                "install_type": "binary",
                "binary_urls": {
                    "darwin/arm64": "https://storage.googleapis.com/mcp-toolbox-for-databases/v1.1.0/darwin/arm64/toolbox",
                    "darwin/amd64": "https://storage.googleapis.com/mcp-toolbox-for-databases/v1.1.0/darwin/amd64/toolbox",
                    "linux/amd64": "https://storage.googleapis.com/mcp-toolbox-for-databases/v1.1.0/linux/amd64/toolbox",
                    "windows/amd64": "https://storage.googleapis.com/mcp-toolbox-for-databases/v1.1.0/windows/amd64/toolbox.exe",
                },
            },
            {
                "id": "npx:@toolbox-sdk/server",
                "name": "MCP Toolbox (NPX)",
                "source": "Google Cloud",
                "description": "Run the Database Toolbox directly via NPX.",
                "install_type": "npx",
                "npx_args": ["-y", "@toolbox-sdk/server", "--stdio"],
            },
        ]
        return [t for t in tools if not query or query.lower() in t["name"].lower()]


class ClaudeCommunityAdapter(MarketplaceAdapter):
    """
    Adapter for searching community-maintained MCP servers on GitHub.
    Ref: https://github.com/modelcontextprotocol/servers
    """

    REPO_API = "https://api.github.com/repos/modelcontextprotocol/servers/contents"

    def search(self, query: str) -> List[Dict[str, Any]]:
        try:
            response = requests.get(self.REPO_API, timeout=10)
            if response.status_code != 200:
                return []

            items = response.json()
            results = []
            for item in items:
                if item["type"] == "dir" and (
                    not query or query.lower() in item["name"].lower()
                ):
                    results.append(
                        {
                            "id": f"github:mcp/{item['name']}",
                            "name": item["name"],
                            "source": "Claude Community",
                            "description": f"Official community server: {item['name']}",
                            "url": item["html_url"],
                            "install_type": "git",
                        }
                    )
            return results
        except Exception as e:
            logger.error(f"GitHub search failed: {e}")
            return []


class GitHubTopicAdapter(MarketplaceAdapter):
    """
    GitHub: repo con topic ``mcp-server`` + fallback per nome (molti MCP non hanno il topic).
    """

    SEARCH_API = "https://api.github.com/search/repositories"

    def _github_search(self, q: str, *, per_page: int = 20) -> List[Dict[str, Any]]:
        headers: Dict[str, str] = {"Accept": "application/vnd.github+json"}
        token = (
            os.getenv("GITHUB_TOKEN") or os.getenv("AION_GITHUB_TOKEN") or ""
        ).strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        response = requests.get(
            self.SEARCH_API,
            params={"q": q, "sort": "stars", "order": "desc", "per_page": per_page},
            headers=headers,
            timeout=12,
        )
        if response.status_code != 200:
            logger.warning("GitHub search %r → HTTP %s", q, response.status_code)
            return []
        data = response.json()
        results: List[Dict[str, Any]] = []
        for repo in data.get("items", []):
            full = repo.get("full_name") or ""
            if "/" not in full:
                continue
            results.append(
                {
                    "id": f"github:{full}",
                    "name": repo.get("name") or full.split("/")[-1],
                    "source": "GitHub",
                    "description": repo.get("description"),
                    "url": repo.get("html_url"),
                    "stars": repo.get("stargazers_count"),
                    "install_type": "git",
                }
            )
        return results

    def search(self, query: str) -> List[Dict[str, Any]]:
        try:
            q_topic = "topic:mcp-server"
            if query:
                q_topic += f" {query}"
            results = self._github_search(q_topic)
            seen = {r.get("id") for r in results}
            if query:
                q_name = f"{query} in:name"
                for row in self._github_search(q_name, per_page=15):
                    rid = row.get("id")
                    if rid and rid not in seen:
                        seen.add(rid)
                        results.append(row)
                # owner/repo esplicito (es. ai-zerolab/mcp-email-server)
                if "/" in query.replace(" ", ""):
                    slug = query.strip().replace(" ", "").strip("/")
                    direct = build_github_market_item(f"https://github.com/{slug}")
                    if direct and not any(
                        r.get("id") == direct.get("id") for r in results
                    ):
                        results.insert(0, direct)
            return results
        except Exception as e:
            logger.error("GitHub search failed: %s", e)
            return []


class AwesomeListAdapter(MarketplaceAdapter):
    """
    Parses community-maintained 'Awesome MCP Servers' lists.
    """

    SOURCES = [
        "https://raw.githubusercontent.com/wong2/awesome-mcp-servers/main/README.md",
        "https://raw.githubusercontent.com/punkpeye/awesome-mcp-servers/main/README.md",
    ]

    def search(self, query: str) -> List[Dict[str, Any]]:
        import re

        results = []
        for url in self.SOURCES:
            try:
                response = requests.get(url, timeout=10)
                if response.status_code != 200:
                    continue

                content = response.text
                pattern = r"- \*\*\[([^\]]+)\]\((https?://[^\)]+)\)\*\*(?: - (.+))?"
                matches = re.finditer(pattern, content)

                for match in matches:
                    name, tool_url, desc = match.groups()
                    if (
                        not query
                        or query.lower() in name.lower()
                        or query.lower() in (desc or "").lower()
                    ):
                        results.append(
                            {
                                "id": f"awesome:{name.lower().replace(' ', '_')}",
                                "name": name,
                                "source": "Awesome List",
                                "description": desc or "No description",
                                "url": tool_url,
                                "install_type": "git"
                                if "github.com" in tool_url
                                else "stdio",
                            }
                        )
            except Exception as e:
                logger.error(f"Awesome list parsing failed for {url}: {e}")
        return results


class HubAggregator:
    def __init__(self):
        self.adapters = [
            AwesomeListAdapter(),
            # OfficialRegistryAdapter()  # Disabilitato: produce voci con install_type="stdio" senza metadati installabili
            GlamaAdapter(),
            GoogleCloudAdapter(),
            ClaudeCommunityAdapter(),
            GitHubTopicAdapter(),
        ]

    def search_all(self, query: str) -> List[Dict[str, Any]]:
        all_results = []
        for adapter in self.adapters:
            all_results.extend(adapter.search(query))

        # Deduplicazione intelligente (per URL o Nome)
        unique_results = []
        seen_urls = set()
        seen_names = set()

        for res in all_results:
            url = res.get("url")
            name = res.get("name")

            if (url and url in seen_urls) or (name and name.lower() in seen_names):
                continue

            if url:
                seen_urls.add(url)
            if name:
                seen_names.add(name.lower())
            unique_results.append(res)

        return unique_results


hub_aggregator = HubAggregator()
