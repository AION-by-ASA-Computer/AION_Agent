import os
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Union
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse
import httpx
import json

# Ensure AION environment and path overrides are initialized first
import src.aion_env  # noqa: F401

# Set up AION-standard logging if available
try:
    from src.observability.logging import setup_logging

    setup_logging()
except ImportError:
    logging.basicConfig(level=logging.INFO)

# Get structured logger
try:
    import structlog

    logger = structlog.get_logger("aion.plane_gateway")
except ImportError:
    logger = logging.getLogger("aion.plane_gateway")

# Quiet down verbose logging from third party libraries
for quiet_logger in ("httpx", "httpcore"):
    logging.getLogger(quiet_logger).setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage the lifecycle of the httpx client to optimize connections."""
    logger.info("Initializing Plane Gateway AsyncClient")
    app.state.client = httpx.AsyncClient(timeout=60.0)
    yield
    logger.info("Closing Plane Gateway AsyncClient")
    await app.state.client.aclose()


app = FastAPI(
    title="Plane Sanitization Gateway",
    description="A lightweight reverse proxy that filters and maps Plane API requests/responses",
    version="1.0.0",
    lifespan=lifespan,
)


from pydantic import BaseModel, Field, model_validator, ConfigDict
from typing import Optional, Any, Dict, List
from uuid import UUID


class PlaneProjectResponse(BaseModel):
    """Schema di sanificazione per i Progetti (POST /projects/)"""

    model_config = ConfigDict(extra="ignore")

    id: UUID
    name: str
    identifier: str = Field(..., description="La chiave del progetto, es. 'PROJ'")
    network: int = Field(default=2)
    workspace: UUID
    description: Optional[str] = ""
    # Campi essenziali di routing o stato
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def pre_validate(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for key in ["id", "workspace"]:
            if key in data and isinstance(data[key], dict) and "id" in data[key]:
                data[key] = data[key]["id"]
        return data


class PlaneIssueResponse(BaseModel):
    """Schema di sanificazione per i Work Items / Issues"""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: UUID
    name: str
    project: UUID = Field(alias="project_id")  # Mappa eventuale project_id in project
    workspace: UUID = Field(alias="workspace_id")
    state: UUID = Field(alias="state_id")
    priority: Optional[str] = "none"
    # La description su Plane CE a volte è un JSON, a volte una stringa html.
    # Usiamo Any per evitare crash di parse, il client MCP se la caverà.
    description: Optional[Any] = None

    # Lista di etichette base
    labels: Optional[List[UUID]] = []

    @model_validator(mode="before")
    @classmethod
    def pre_validate(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        # Mappa nested dict objects o normalizza alias/field names
        for key in [
            "id",
            "project",
            "project_id",
            "workspace",
            "workspace_id",
            "state",
            "state_id",
        ]:
            if key in data and isinstance(data[key], dict) and "id" in data[key]:
                data[key] = data[key]["id"]

        # Estrai label id se presenti come dict
        if "labels" in data and isinstance(data["labels"], list):
            new_labels = []
            for item in data["labels"]:
                if isinstance(item, dict) and "id" in item:
                    new_labels.append(item["id"])
                else:
                    new_labels.append(item)
            data["labels"] = new_labels
        return data


def sanitize_project_payload(data: Any) -> Any:
    """Sanitize projects list, paginated results, or single dict."""
    if isinstance(data, list):
        sanitized = []
        for x in data:
            try:
                sanitized.append(PlaneProjectResponse(**x).model_dump(mode="json"))
            except Exception as e:
                logger.warn(
                    "Failed to sanitize project with Pydantic model",
                    error=str(e),
                    item=x,
                )
                sanitized.append(x)
        return sanitized
    elif isinstance(data, dict):
        if "results" in data and isinstance(data["results"], list):
            sanitized_results = []
            for x in data["results"]:
                try:
                    sanitized_results.append(
                        PlaneProjectResponse(**x).model_dump(mode="json")
                    )
                except Exception as e:
                    logger.warn(
                        "Failed to sanitize project in results list with Pydantic model",
                        error=str(e),
                        item=x,
                    )
                    sanitized_results.append(x)
            data["results"] = sanitized_results
            return data
        else:
            try:
                return PlaneProjectResponse(**data).model_dump(mode="json")
            except Exception as e:
                logger.warn(
                    "Failed to sanitize project dict with Pydantic model", error=str(e)
                )
                return data
    return data


def sanitize_issue_payload(data: Any) -> Any:
    """Sanitize issues/work-items list, paginated results, or single dict."""
    if isinstance(data, list):
        sanitized = []
        for x in data:
            try:
                sanitized.append(PlaneIssueResponse(**x).model_dump(mode="json"))
            except Exception as e:
                logger.warn(
                    "Failed to sanitize issue with Pydantic model", error=str(e), item=x
                )
                sanitized.append(x)
        return sanitized
    elif isinstance(data, dict):
        if "results" in data and isinstance(data["results"], list):
            sanitized_results = []
            for x in data["results"]:
                try:
                    sanitized_results.append(
                        PlaneIssueResponse(**x).model_dump(mode="json")
                    )
                except Exception as e:
                    logger.warn(
                        "Failed to sanitize issue in results list with Pydantic model",
                        error=str(e),
                        item=x,
                    )
                    sanitized_results.append(x)
            data["results"] = sanitized_results
            return data
        else:
            try:
                return PlaneIssueResponse(**data).model_dump(mode="json")
            except Exception as e:
                logger.warn(
                    "Failed to sanitize issue dict with Pydantic model", error=str(e)
                )
                return data
    return data


async def sanitize_inbound_payload(method: str, path: str, body: bytes) -> bytes:
    """
    Intercetta le richieste dell'agente verso Plane e rimuove i campi
    che causano i crash post-creazione sul backend di Plane CE.
    """
    if method in ["POST", "PATCH"] and "projects" in path.lower():
        if not body:
            return body

        try:
            data = json.loads(body.decode("utf-8"))

            # Manteniamo SOLO i campi core di base sicuri al 100%.
            # Tutto il resto (project_lead, cover_image, emoji, ecc.) viene scartato.
            safe_data = {"name": data.get("name"), "identifier": data.get("identifier")}

            for field in ["description", "network", "project_lead", "default_assignee"]:
                if data.get(field) is not None:
                    safe_data[field] = data.get(field)

            # Aggiungi description e network solo se presenti e non nulli
            if data.get("description"):
                safe_data["description"] = data.get("description")
            if data.get("network") is not None:
                safe_data["network"] = data.get("network")

            logger.info(
                "Sanitized inbound project payload",
                original_keys=list(data.keys()),
                safe_keys=list(safe_data.keys()),
            )

            return json.dumps(safe_data).encode("utf-8")
        except Exception as e:
            logger.error("Failed to parse inbound body for sanitization", error=str(e))

    return body


@app.api_route(
    "/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]
)
async def proxy_catch_all(request: Request, path: str) -> Response:
    """Intercept, rewrite, and forward all requests to the local Plane instance."""
    # Determine the target Plane Base URL
    plane_local_url = os.getenv("PLANE_LOCAL_URL") or os.getenv("PLANE_BASE_URL")
    if not plane_local_url:
        logger.error(
            "Configuration error: Neither PLANE_LOCAL_URL nor PLANE_BASE_URL is set in environment"
        )
        raise HTTPException(
            status_code=500,
            detail="Plane Sanitization Gateway Configuration Error: PLANE_LOCAL_URL or PLANE_BASE_URL must be set.",
        )

    plane_local_url = plane_local_url.rstrip("/")

    # If the user included /api/v1/ inside the local base URL config, strip it to prevent duplicate pathing
    if "api/v1" in plane_local_url:
        plane_local_url = plane_local_url.replace("/api/v1", "").rstrip("/")

    # 1. Routing / Path Rewriting: map work-items to issues for local instance
    rewritten_path = path
    if "work-items" in path:
        rewritten_path = path.replace("work-items", "issues")

    target_url = f"{plane_local_url}/{rewritten_path}"

    # 2. Inbound Query Parameter Manipulation: map 'q' to 'search' for GET requests
    params = dict(request.query_params)
    if request.method == "GET" and "q" in params:
        params["search"] = params.pop("q")

    # 3. Header Extraction: scartiamo Host e Content-Length. httpx ricalcolerà la lunghezza automaticamente.
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ["host", "content-length"]
    }

    # Extract body e sanificazione
    body = await request.body()
    body = await sanitize_inbound_payload(request.method, rewritten_path, body)

    if "content-length" in headers:
        headers["content-length"] = str(len(body))

    logger.info(
        "Inbound request",
        method=request.method,
        inbound_path=path,
        rewritten_path=rewritten_path,
        target_url=target_url,
        query_params=params,
    )

    client: httpx.AsyncClient = request.app.state.client

    try:
        response = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            params=params,
            content=body,
            follow_redirects=True,
        )
    except Exception as e:
        logger.exception("Proxy request failed to target", target_url=target_url)
        raise HTTPException(
            status_code=502,
            detail=f"Bad Gateway: Failed to forward request to local Plane: {str(e)}",
        )

    logger.info(
        "Outbound response received",
        status_code=response.status_code,
        target_url=target_url,
    )

    # 4. Outbound Response Handling
    # If the status code indicates an error (4xx or 5xx), forward the response inalterato
    # 4. Outbound Response Handling
    if response.status_code >= 400:
        # --- IDEMPOTENCY RECOVERY: Salvezza dai Fallimenti Parziali ---
        if (
            response.status_code == 400
            and request.method == "POST"
            and "projects" in path.lower()
        ):
            logger.warn(
                "Ricevuto 400 su creazione progetto. Controllo se è un fallimento parziale..."
            )
            try:
                req_data = json.loads(body.decode("utf-8"))
                proj_name = req_data.get("name")
                if proj_name:
                    # Facciamo una GET al volo per vedere se il progetto esiste già
                    check_resp = await client.get(
                        url=target_url, headers=headers, params={"search": proj_name}
                    )
                    if check_resp.status_code == 200:
                        resp_json = check_resp.json()
                        results = (
                            resp_json.get("results", [])
                            if isinstance(resp_json, dict)
                            else resp_json
                        )
                        if isinstance(results, list):
                            for p in results:
                                if p.get("name") == proj_name:
                                    logger.info(
                                        "Il progetto è stato creato nonostante il 400. Recupero in corso...",
                                        project_id=p.get("id"),
                                    )
                                    sanitized = sanitize_project_payload(p)
                                    # Trasformiamo l'errore in un successo per l'agente
                                    return JSONResponse(
                                        content=sanitized, status_code=201
                                    )
            except Exception as ex:
                logger.error("Controllo di recovery fallito", error=str(ex))
        # ---------------------------------------------------------------

        logger.warn(
            "Forwarding error response from Plane inalterato",
            status_code=response.status_code,
            target_url=target_url,
        )

        # Keep response headers except content-length/transfer-encoding
        resp_headers = {
            k: v
            for k, v in response.headers.items()
            if k.lower()
            not in ("content-length", "transfer-encoding", "content-encoding")
        }
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=resp_headers,
        )

    # For successful responses, attempt JSON sanitization
    is_json = "application/json" in response.headers.get("content-type", "").lower()
    if is_json:
        try:
            data = response.json()
        except ValueError:
            logger.warn(
                "Response headers declared JSON, but body failed to decode",
                target_url=target_url,
            )
            is_json = False

    if is_json:
        lower_path = path.lower()
        sanitized_data = data

        # Check if the path concerns projects
        if "projects" in lower_path:
            sanitized_data = sanitize_project_payload(data)
            logger.info("Sanitized projects response payload", target_url=target_url)

        # Check if the path concerns issues (or work-items)
        elif "work-items" in lower_path or "issues" in lower_path:
            sanitized_data = sanitize_issue_payload(data)
            logger.info("Sanitized issues response payload", target_url=target_url)

        return JSONResponse(
            content=sanitized_data,
            status_code=response.status_code,
        )

    # If response is not JSON or successfully processed, return raw response content
    resp_headers = {
        k: v
        for k, v in response.headers.items()
        if k.lower() not in ("content-length", "transfer-encoding", "content-encoding")
    }
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=resp_headers,
    )


if __name__ == "__main__":
    import uvicorn

    port_str = os.getenv("GATEWAY_PORT", "8010")
    try:
        port = int(port_str)
    except ValueError:
        port = 8010

    logger.info("Starting Plane Sanitization Gateway", host="0.0.0.0", port=port)
    uvicorn.run("src.gateway.plane.main:app", host="0.0.0.0", port=port, reload=True)
