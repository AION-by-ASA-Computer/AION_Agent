---
name: khub_rag_tool
description: Retrieve documents and general information about the company from khub_rag MCP server
tags: [memory, rag, documentation, knowledge, tool]
status: verified
source: curated
version: 1
---

## Knowledge Hub (khub_rag) — Search & Document Retrieval

### Available Tools
| Tool | Server | Purpose |
|------|--------|---------|
| `list_files_tree` | `khub_rag` | Navigate the folder structure to identify relevant directories and exclude unrelated ones — always call this FIRST, before any `search_company_documents` call|
| `search_company_documents` | `khub_rag` | Dual-purpose tool:
  1. SEMANTIC SEARCH: find relevant content across documents when 
     the file location is unknown (use broad queries, no filter)
  2. CONTENT RETRIEVAL: read the content of a specific file when 
     the path is already known (use filters: {"file_path": "..."} 
     with a generic query like the file name)
NEVER call this before list_files_tree has been called in the same turn. |
| `search_files_by_name` | `khub_rag` | Search files by name |
| `pdf_page_extractor` | `khub_rag` | Targeted PDF page extraction: extracts one or more specific pages 
from a PDF file when the agent needs to inspect precise sections in depth.
Requires the **full file path** (obtained from a prior `search_company_documents` or `search_files_by_name` call) and an **array of page ranges** to extract.
Use this ONLY after the file path is already known — NEVER as a first step. |
| `get_file_download_url` | `khub_rag` | Generate a pre-signed URL (valid for 2 minutes) to directly download a file stored on RustFS. Requires the **full file path**. |
| `request_file_upload` | `khub_rag` | Generate a special token and its relative parameters to upload a file to the Knowledge Hub. Requires the **filename** and optional **folder_id** parameter. |
---

### When to Use khub_rag Tools

Always query khub_rag when the user's request involves any of the following:

- **Company documents** — transport documents, invoices, contracts, purchase orders, or any records related to clients or suppliers
- **Internal IT support** — issues with company devices, software, configurations, or IT procedures
- **Company knowledge & policies** — operational procedures, guidelines, internal regulations, manuals, or onboarding material
- **Document discovery** — any question of the form *"do we have…"*, *"where can I find…"*, *"what documents exist for…"*, *"can the document X"*, *"show me the document X"*
- **Deep PDF inspection** — when a document has already been located and the agent 
  needs to examine specific pages in detail (e.g. a particular clause in a contract, 
  a specific page of a manual, a single invoice sheet)

### Default Workflow — follow this order without exception:

1. `list_files_tree` (root) — get the top-level structure.

2. If a relevant folder is found but contains only subfolders (no files 
   visible), call `list_files_tree` again with that folder path.
   Repeat until you reach file level.

3. If after repeated `list_files_tree` calls you still cannot locate 
   the file (tree too deep or file not visible), call 
   `search_files_by_name`:
   - set `query` to the file name or keyword the user mentioned
   - set `folder_path` to the deepest relevant path found so far
   This returns the full file path. 
   Do NOT use `search_files_by_name` as a replacement for step 1-2.

4. `search_company_documents` — use it in RETRIEVAL mode: pass the 
   path found in step 2 or 3 as filter, and use the file name or 
   topic as query. This reads the actual file content.
   `filters: {"file_path": "/path/identified/above"}`
   `queries: ["registro manutenzioni", "maintenance log"]`


5. *(Optional)* `pdf_page_extractor` — use it only if, after reading the document 
   content in step 4, specific pages require deeper inspection (e.g. a table, a 
   diagram, a dense legal clause).
   - `file_path`: the full path already identified in steps 2–3
   - `pages`: array of page ranges to extract, e.g. `[[3,5], [12,12]]`
   Do NOT use it before the file path is known.


6. **CITATION REQUIRED**: every piece of information taken from documents retrieved 
   MUST be cited inline immediately after the claim, using 
   the path returned by the tool. See Citation Rules below.


   
### Trigger Examples

| User Query | Recommended Action | Why |
|------------|--------------------|-----|
| *"What transport documents do we have for client X?"* | `list_files_tree` → `search_company_documents` | Content-based search is more reliable than folder navigation |
| *"I have a problem with my work laptop"* | `list_files_tree` → `search_company_documents` | — |
| *"What is the procedure for…?"* | `list_files_tree` → `search_company_documents` | — |
| *"Does a document about X exist?"* | `list_files_tree` → `search_company_documents` | — |
| *"What folders/categories/ of X do we have?"* | `list_files_tree` | The user is asking about structure, not content |
| *"Show me everything inside the Contracts folder"* | `list_files_tree` | Explicit folder browsing request |
| *"I searched but got no results — can you look around?"* | `list_files_tree` → then `search_company_documents` | Fallback when search yields nothing useful |
| *"Can you show me page 7 and 12 of contract X?"* | `list_files_tree` → `search_company_documents` → `pdf_page_extractor` | User references specific pages of a known document |
| *"Download/get the actual file X"* | `list_files_tree` → `search_files_by_name` → `get_file_download_url` → Sandbox Download Script | User wants to download a file locally to their session workspace |
| *"Upload/save file X to Knowledge Hub"* | `request_file_upload` → Sandbox Upload Script | User wants to upload or save a file from their workspace to the company Knowledge Hub |


### File Downloading and Sandbox Ingestion Workflow

When the user asks to download, fetch, or retrieve a file (or when you need to inspect the binary file locally in the workspace):
1. **Get the Download URL**: Call `get_file_download_url` with the exact `file_path`.
2. **Extract the URL**: Retrieve the pre-signed URL string from the tool output.
3. **Write a Download Script**: Call `sandbox_write_workspace_file` to write a Python script (e.g. `workspace/download_file.py`) using Python's standard `urllib.request` library:
   ```python
   import urllib.request
   import os

   url = "PRE_SIGNED_URL_FROM_TOOL"
   output_path = "workspace/FILENAME.ext" # e.g. workspace/documento.pdf

   try:
       os.makedirs(os.path.dirname(output_path), exist_ok=True)
       urllib.request.urlretrieve(url, output_path)
       print(f"File downloaded successfully to: {output_path}")
       print(f"Size: {os.path.getsize(output_path)} bytes")
   except Exception as e:
       print(f"Error: {e}")
       exit(1)
   ```
4. **Execute the Script**: Call `sandbox_run_python_file(relative_path="workspace/download_file.py")` to download the file directly into your session's sandboxed environment.
5. **Verify**: Use `sandbox_list_files(subdir="workspace")` or files tools to confirm the file has been successfully downloaded.


### File Uploading and Sandbox Export Workflow

When the user asks to upload, export, or save a local file to the Knowledge Hub (or when you have created/modified a file in the sandboxed workspace that needs to be persisted in the company storage):
1. **Request the Upload Parameters**: Call `request_file_upload` with:
   - `filename`: the exact name of the file to upload (e.g. `"report.pdf"`).
   - `folder_id`: the target folder path/ID (e.g. `"Folder/Subfolder"`). If you want to upload to the root directory, pass `"null"` or leave it as `None`.
2. **Extract the Upload Data**: Retrieve the `upload_url`, `token`, and `folder_id` (which defaults to `"null"` or `"root"`) from the tool response.
3. **Write an Upload Script**: Call `sandbox_write_workspace_file` to write a Python script (e.g. `workspace/upload_file.py`) that reads the local file and POST it to the `upload_url` using standard HTTP multipart/form-data.

   Here is the standard, simple implementation using the `urllib` library:

   ```python
   import urllib.request
   import mimetypes
   import uuid
   import os

   url = "UPLOAD_URL"
   token = "TOKEN"
   filepath = "workspace/FILENAME.ext"
   folder_id = "FOLDER_ID_OR_NULL"

   try:
       if not os.path.exists(filepath):
           raise FileNotFoundError(f"Source file not found at: {filepath}")

       boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
       filename = os.path.basename(filepath)
       
       with open(filepath, "rb") as f:
           file_content = f.read()
           
       mime_type, _ = mimetypes.guess_type(filepath)
       mime_type = mime_type or "application/octet-stream"
       
       parts = []
       
       # folder_id field
       parts.append(f"--{boundary}".encode("utf-8"))
       parts.append(b'Content-Disposition: form-data; name="folder_id"')
       parts.append(b"")
       parts.append(str(folder_id).encode("utf-8"))
       
       # file field
       parts.append(f"--{boundary}".encode("utf-8"))
       parts.append(f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode("utf-8"))
       parts.append(f"Content-Type: {mime_type}".encode("utf-8"))
       parts.append(b"")
       parts.append(file_content)
       
       parts.append(f"--{boundary}--".encode("utf-8"))
       parts.append(b"")
       
       body = b"\r\n".join(parts)
       
       headers = {
           "Authorization": f"Bearer {token}",
           "Content-Type": f"multipart/form-data; boundary={boundary}",
           "Content-Length": str(len(body))
       }
       
       req = urllib.request.Request(url, data=body, headers=headers, method="POST")
       with urllib.request.urlopen(req) as response:
           resp_body = response.read().decode("utf-8")
           print(f"Status Code: {response.status}")
           print(f"Response: {resp_body}")
           print("Upload completed successfully!")
   except Exception as e:
       print(f"Error during upload: {e}")
       exit(1)
   ```

4. **Execute the Script**: Call `sandbox_run_python_file(relative_path="workspace/upload_file.py")` to perform the upload.
5. **Verify**: Ensure the tool output reports a `200` or `201` status code and says "Upload completed successfully!".


### Citation Rules — follow strictly

After every sentence or paragraph that draws information from a retrieved 
document, append an inline citation in this exact format:

  [filename.ext](absolute/path/to/file)

Rules:
- MANDATORY: every sentence that uses information from a document MUST 
  have its own inline citation placed immediately after it — period.
  A "Sources" section alone is NOT sufficient and is NOT acceptable.
  If a response has no inline citations, it is WRONG regardless of 
  whether the Sources section is present.
- If a single claim is supported by **multiple documents**, chain citations:
  [[file1.pdf]](/path/file1.pdf) [[file2.xlsx]](/path/file2.xlsx)
- At the end of the response, always add a **Sources** section 
  listing every cited document once, in this format:

  ### Sources
  - [filename1.ext](/path/to/filename1.ext)
  - [filename2.ext](/path/to/filename2.ext)

- Never fabricate paths. Only cite documents whose path was returned by 
  `search_company_documents` or `search_files_by_name`.
- If no document was retrieved, do not cite anything.



### Example of a correctly cited response

WRONG — inline citations missing, only Sources section:
  "The maintenance interval is every 6 months. The procedure requires 
   a certified technician.

   ### Sources
   - [manuale-manutenzione.pdf](/docs/manuale-manutenzione.pdf)"

CORRECT — every sentence has its own inline citation:
  "The maintenance interval is every 6 months 
   [manuale-manutenzione.pdf](/docs/manuale-manutenzione.pdf). 
   The procedure requires a certified technician 
   [procedura-tecnici.pdf](/docs/procedura-tecnici.pdf).

   ### Sources
   - [manuale-manutenzione.pdf](/docs/manuale-manutenzione.pdf)
   - [procedura-tecnici.pdf](/docs/procedura-tecnici.pdf)"