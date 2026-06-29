"use client";

import React from "react";

export default function UserDBDetail() {
  return (
    <div className="p-8 text-gray-500 italic">Visualizzazione Dettaglio Agent DB non disponibile.</div>
  );
}

/*
import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api/headers"
import { useParams } from "next/navigation";
import Link from "next/link";
import { apiBase } from "@/lib/api";
import {
  ChevronLeft,
  RefreshCw,
  Play,
  Plus,
  Trash2,
  FileDown,
  FileUp,
} from "lucide-react";

export default function OriginalUserDBDetail() {
  const params = useParams();
  const userId = params.userId as string;
  const [selectedSchema, setSelectedSchema] = useState("");
  const [selectedTable, setSelectedTable] = useState("");
  const [data, setData] = useState<any>(null);
  const [rowsData, setRowsData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [rowsLoading, setRowsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"browse" | "schema" | "sql" | "io">("browse");
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [sortBy, setSortBy] = useState("_id");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [sql, setSql] = useState("SELECT 1 as ok");
  const [sqlResult, setSqlResult] = useState<any>(null);
  const [editingCell, setEditingCell] = useState<{ rowId: any; column: string } | null>(null);
  const [editCellValue, setEditCellValue] = useState("");
  const [newTableName, setNewTableName] = useState("new_table");
  const [createPayload, setCreatePayload] = useState(
    JSON.stringify([{ name: "name", type: "TEXT", nullable: true, description: "Field" }], null, 2)
  );
  const [renameTableName, setRenameTableName] = useState("");
  const [newColumnName, setNewColumnName] = useState("new_col");
  const [newColumnType, setNewColumnType] = useState("TEXT");
  const [importContent, setImportContent] = useState("[]");
  const embedded = useMemo(() => {
    if (typeof window === "undefined") return false;
    return new URLSearchParams(window.location.search).get("embedded") === "1";
  }, []);
  const embedToken = useMemo(() => {
    if (typeof window === "undefined") return "";
    return new URLSearchParams(window.location.search).get("token") || "";
  }, []);

  const authHeaders = useMemo(() => {
    const h: Record<string, string> = { "X-AION-User-Id": userId };
    if (embedToken) h["X-AION-Embed-Token"] = embedToken;
    return h;
  }, [userId, embedToken]);

  const postJson = async (url: string, method: string, body?: any) => {
    const resp = await apiFetch(url, {
      method,
      headers: { "Content-Type": "application/json", ...authHeaders },
      body: body ? JSON.stringify(body) : undefined,
    });
    const text = await resp.text();
    if (!resp.ok) throw new Error(text || `HTTP ${resp.status}`);
    try {
      return JSON.parse(text);
    } catch {
      return {};
    }
  };

  const fetchDetail = async () => {
    setLoading(true);
    try {
      const resp = await apiFetch(`${apiBase()}/admin/agent-db/${userId}/detail`, { headers: authHeaders });
      if (!resp.ok) throw new Error("Failed to fetch user DB detail");
      const json = await resp.json();
      setData(json);
      if (!selectedSchema || !selectedTable) {
        const s = json?.schemas?.[0];
        const t = s?.tables?.[0];
        if (s?.schema_name && t?.table_name) {
          setSelectedSchema(s.schema_name);
          setSelectedTable(t.table_name);
        }
      }
      setError(null);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchRows = async () => {
    if (!selectedSchema || !selectedTable) return;
    setRowsLoading(true);
    try {
      const resp = await apiFetch(
        `${apiBase()}/admin/agent-db/${userId}/${selectedSchema}/${selectedTable}/rows?page=${page}&page_size=25&q=${encodeURIComponent(
          q
        )}&sort_by=${encodeURIComponent(sortBy)}&sort_dir=${sortDir}`
      , { headers: authHeaders });
      if (!resp.ok) throw new Error("Failed to fetch rows");
      setRowsData(await resp.json());
      setError(null);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setRowsLoading(false);
    }
  };

  const runAction = async (fn: () => Promise<any>) => {
    try {
      await fn();
      await fetchDetail();
      await fetchRows();
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Operation failed");
    }
  };

  const handleSaveCell = async (row: any, column: string) => {
    if (!editingCell || editingCell.rowId !== row._id || editingCell.column !== column) return;
    
    const originalValue = String(row[column] ?? "");
    if (editCellValue === originalValue) {
      setEditingCell(null);
      return;
    }

    setEditingCell(null);

    await runAction(async () => {
      const obj = { ...row };
      delete obj._id;
      
      let finalValue: any = editCellValue;
      if (row[column] !== null && row[column] !== undefined) {
        if (typeof row[column] === "number") {
          const num = Number(editCellValue);
          if (!isNaN(num)) {
            finalValue = num;
          }
        } else if (typeof row[column] === "boolean") {
          if (editCellValue.toLowerCase() === "true") finalValue = true;
          else if (editCellValue.toLowerCase() === "false") finalValue = false;
        }
      } else {
        const num = Number(editCellValue);
        if (editCellValue !== "" && !isNaN(num)) {
          finalValue = num;
        }
      }
      
      obj[column] = finalValue;

      await postJson(
        `${apiBase()}/admin/agent-db/${userId}/${selectedSchema}/${selectedTable}/rows/${row._id}`,
        "PATCH",
        { row: obj, tenant_id: "default" }
      );
    });
  };

  useEffect(() => {
    if (userId) fetchDetail();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, authHeaders]);

  useEffect(() => {
    fetchRows();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSchema, selectedTable, page, q, sortBy, sortDir]);

  if (loading && !data) return <div className="p-6 text-gray-400">Loading DB editor...</div>;

  return (
    <div className="bg-[#0a0a0a] min-h-screen text-white">
      <div className={embedded ? "w-full p-4" : "max-w-6xl mx-auto"}>
        {!embedded && (
          <header className="mb-6">
            <div className="flex items-center gap-4 text-sm text-gray-500 mb-3">
              <Link href="/agent-db" className="hover:text-white transition-colors flex items-center gap-1">
                <ChevronLeft className="w-4 h-4" />
                Agent DB Explorer
              </Link>
              <span>/</span>
              <span className="text-white font-mono">{userId}</span>
            </div>
            <h1 className="text-2xl font-bold">DB Editor</h1>
          </header>
        )}

        {error && <div className="mb-3 p-2 text-xs bg-red-500/10 border border-red-500/20 rounded">{error}</div>}

        <div className="flex border-b border-white/10 mb-3 gap-5 text-xs uppercase tracking-wider">
          <button onClick={() => setTab("browse")} className={tab === "browse" ? "text-blue-400 pb-2" : "text-gray-500 pb-2"}>Browse</button>
          <button onClick={() => setTab("schema")} className={tab === "schema" ? "text-blue-400 pb-2" : "text-gray-500 pb-2"}>Schema</button>
          <button onClick={() => setTab("sql")} className={tab === "sql" ? "text-blue-400 pb-2" : "text-gray-500 pb-2"}>SQL</button>
          <button onClick={() => setTab("io")} className={tab === "io" ? "text-blue-400 pb-2" : "text-gray-500 pb-2"}>Import/Export</button>
        </div>

        <div className="grid grid-cols-12 gap-4">
          <div className="col-span-12 md:col-span-3 bg-[#111] border border-white/10 rounded-xl p-3 max-h-[76vh] overflow-auto">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs uppercase tracking-widest text-gray-400">Schemas</h3>
              <button onClick={fetchDetail} className="p-1 rounded hover:bg-white/10"><RefreshCw className="w-4 h-4" /></button>
            </div>
            {(data?.schemas || []).map((s: any) => (
              <div key={s.schema_name} className="mb-2">
                <div className="text-sm font-semibold text-blue-400">{s.schema_name}</div>
                <div className="ml-2 mt-1 space-y-1">
                  {(s.tables || []).map((t: any) => {
                    const active = selectedSchema === s.schema_name && selectedTable === t.table_name;
                    return (
                      <button
                        key={t.table_name}
                        onClick={() => {
                          setSelectedSchema(s.schema_name);
                          setSelectedTable(t.table_name);
                          setPage(1);
                        }}
                        className={`w-full text-left px-2 py-1 rounded text-xs ${active ? "bg-blue-600/20 text-white" : "hover:bg-white/5 text-gray-300"}`}
                      >
                        {t.table_name}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>

          <div className="col-span-12 md:col-span-9 space-y-3">
            <div className="bg-[#111] border border-white/10 rounded-xl p-3 flex flex-wrap items-center gap-2">
              <div className="text-sm font-semibold">{selectedSchema}.{selectedTable}</div>
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search" className="bg-black/30 border border-white/10 rounded px-2 py-1 text-xs" />
              <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} className="bg-black/30 border border-white/10 rounded px-2 py-1 text-xs">
                {(rowsData?.columns || ["_id"]).map((c: string) => <option key={c} value={c}>{c}</option>)}
              </select>
              <select value={sortDir} onChange={(e) => setSortDir(e.target.value as "asc" | "desc")} className="bg-black/30 border border-white/10 rounded px-2 py-1 text-xs">
                <option value="asc">asc</option>
                <option value="desc">desc</option>
              </select>
              <button onClick={fetchRows} className="px-2 py-1 rounded bg-white/10 text-xs">View</button>
              <button
                onClick={() => runAction(async () => {
      const exp = await apiFetch(`${apiBase()}/admin/agent-db/${userId}/${selectedSchema}/${selectedTable}/export?format=json`, { headers: authHeaders }).then((r) => r.json());
                  navigator.clipboard.writeText(JSON.stringify(exp.rows || [], null, 2));
                })}
                className="px-2 py-1 rounded bg-white/10 text-xs"
              ><FileDown className="w-3 h-3 inline mr-1" />Copy Export</button>
            </div>

            {tab === "browse" && (
              <div className="bg-[#111] border border-white/10 rounded-xl overflow-auto max-h-[62vh]">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-white/10">
                      {(rowsData?.columns || []).map((c: string) => <th key={c} className="px-2 py-2">{c}</th>)}
                      <th className="px-2 py-2">actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rowsLoading && <tr><td colSpan={99} className="p-4 text-gray-400">Loading...</td></tr>}
                    {!rowsLoading && (rowsData?.rows || []).map((r: any) => (
                      <tr key={r._id} className="border-b border-white/5">
                        {(rowsData?.columns || []).map((c: string) => {
                          const isEditing = editingCell?.rowId === r._id && editingCell?.column === c;
                          const isId = c === "_id";

                          return (
                            <td
                              key={c}
                              className={`px-2 py-1 whitespace-nowrap ${
                                isId
                                  ? "text-gray-500 font-mono select-all cursor-default"
                                  : "hover:bg-white/5 transition-colors cursor-pointer select-none"
                              }`}
                              onDoubleClick={() => {
                                if (isId) return;
                                setEditingCell({ rowId: r._id, column: c });
                                setEditCellValue(String(r[c] ?? ""));
                              }}
                            >
                              {isEditing ? (
                                <input
                                  type="text"
                                  value={editCellValue}
                                  onChange={(e) => setEditCellValue(e.target.value)}
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter") {
                                      handleSaveCell(r, c);
                                    } else if (e.key === "Escape") {
                                      setEditingCell(null);
                                    }
                                  }}
                                  onBlur={() => handleSaveCell(r, c)}
                                  className="bg-black/50 text-white border border-blue-500 rounded px-1.5 py-0.5 text-xs w-full focus:outline-none focus:ring-1 focus:ring-blue-500"
                                  autoFocus
                                />
                              ) : r[c] === null || r[c] === undefined || String(r[c]) === "" ? (
                                <span className="text-gray-600 italic font-mono">(null)</span>
                              ) : (
                                String(r[c])
                              )}
                            </td>
                          );
                        })}
                        <td className="px-2 py-1">
                          <button
                            onClick={() =>
                              runAction(async () => {
                                await postJson(
                                  `${apiBase()}/admin/agent-db/${userId}/${selectedSchema}/${selectedTable}/rows/${r._id}`,
                                  "DELETE"
                                );
                              })
                            }
                            className="p-1 rounded hover:bg-red-500/10 text-red-400 hover:text-red-300 transition-colors"
                            title="Delete Row"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="p-2 flex justify-between text-xs">
                  <span>Page {rowsData?.page || 1}/{rowsData?.total_pages || 1} (total {rowsData?.total || 0})</span>
                  <div>
                    <button onClick={() => setPage((p) => Math.max(1, p - 1))} className="px-2">Prev</button>
                    <button onClick={() => setPage((p) => p + 1)} className="px-2">Next</button>
                  </div>
                </div>
              </div>
            )}

            {tab === "schema" && (
              <div className="grid md:grid-cols-2 gap-3">
                <div className="bg-[#111] border border-white/10 rounded-xl p-3">
                  <h4 className="text-sm mb-2">Create Table</h4>
                  <input value={newTableName} onChange={(e) => setNewTableName(e.target.value)} className="w-full mb-2 bg-black/30 border border-white/10 rounded px-2 py-1 text-xs" />
                  <textarea value={createPayload} onChange={(e) => setCreatePayload(e.target.value)} className="w-full h-40 bg-black/30 border border-white/10 rounded px-2 py-1 text-xs" />
                  <button onClick={() => runAction(async () => { await postJson(`${apiBase()}/admin/agent-db/${userId}/${selectedSchema}/tables/${newTableName}`, "POST", { columns: JSON.parse(createPayload), tenant_id: "default" }); })} className="mt-2 px-2 py-1 bg-blue-600/30 rounded text-xs"><Plus className="w-3 h-3 inline mr-1" />Create</button>
                </div>
                <div className="bg-[#111] border border-white/10 rounded-xl p-3">
                  <h4 className="text-sm mb-2">Rename/Add Column/Drop</h4>
                  <input value={renameTableName} onChange={(e) => setRenameTableName(e.target.value)} placeholder="new table name" className="w-full mb-2 bg-black/30 border border-white/10 rounded px-2 py-1 text-xs" />
                  <button onClick={() => runAction(async () => { await postJson(`${apiBase()}/admin/agent-db/${userId}/${selectedSchema}/tables/${selectedTable}/rename`, "PATCH", { new_table_name: renameTableName, tenant_id: "default" }); setSelectedTable(renameTableName); })} className="px-2 py-1 bg-white/10 rounded text-xs mr-2">Rename</button>
                  <div className="my-2 flex gap-2">
                    <input value={newColumnName} onChange={(e) => setNewColumnName(e.target.value)} placeholder="column" className="flex-1 bg-black/30 border border-white/10 rounded px-2 py-1 text-xs" />
                    <input value={newColumnType} onChange={(e) => setNewColumnType(e.target.value)} placeholder="type" className="w-24 bg-black/30 border border-white/10 rounded px-2 py-1 text-xs" />
                  </div>
                  <button onClick={() => runAction(async () => { await postJson(`${apiBase()}/admin/agent-db/${userId}/${selectedSchema}/${selectedTable}/columns`, "POST", { tenant_id: "default", column: { name: newColumnName, type: newColumnType } }); })} className="px-2 py-1 bg-white/10 rounded text-xs mr-2">Add Column</button>
                  <button onClick={() => runAction(async () => { await postJson(`${apiBase()}/admin/agent-db/${userId}/${selectedSchema}/tables/${selectedTable}`, "DELETE"); })} className="px-2 py-1 bg-red-600/30 rounded text-xs">Drop Table</button>
                </div>
              </div>
            )}

            {tab === "sql" && (
              <div className="bg-[#111] border border-white/10 rounded-xl p-3">
                <textarea value={sql} onChange={(e) => setSql(e.target.value)} className="w-full h-36 bg-black/30 border border-white/10 rounded px-2 py-1 text-xs" />
                <button onClick={() => runAction(async () => { const out = await postJson(`${apiBase()}/admin/agent-db/${userId}/sql`, "POST", { query: sql, tenant_id: "default", allow_write: true }); setSqlResult(out); })} className="mt-2 px-2 py-1 bg-blue-600/30 rounded text-xs"><Play className="w-3 h-3 inline mr-1" />Run SQL</button>
                <pre className="mt-3 text-xs bg-black/40 p-2 rounded overflow-auto max-h-64">{JSON.stringify(sqlResult, null, 2)}</pre>
              </div>
            )}

            {tab === "io" && (
              <div className="bg-[#111] border border-white/10 rounded-xl p-3">
                <textarea value={importContent} onChange={(e) => setImportContent(e.target.value)} className="w-full h-40 bg-black/30 border border-white/10 rounded px-2 py-1 text-xs" />
                <div className="mt-2 flex gap-2">
                  <button onClick={() => runAction(async () => { await postJson(`${apiBase()}/admin/agent-db/${userId}/${selectedSchema}/${selectedTable}/import`, "POST", { format: "json", mode: "append", content: importContent, tenant_id: "default" }); })} className="px-2 py-1 bg-white/10 rounded text-xs"><FileUp className="w-3 h-3 inline mr-1" />Import Append</button>
                  <button onClick={() => runAction(async () => { await postJson(`${apiBase()}/admin/agent-db/${userId}/${selectedSchema}/${selectedTable}/import`, "POST", { format: "json", mode: "replace", content: importContent, tenant_id: "default" }); })} className="px-2 py-1 bg-white/10 rounded text-xs">Import Replace</button>
                  <button onClick={() => runAction(async () => { const exp = await apiFetch(`${apiBase()}/admin/agent-db/${userId}/${selectedSchema}/${selectedTable}/export?format=json`, { headers: authHeaders }).then((r) => r.json()); setImportContent(JSON.stringify(exp.rows || [], null, 2)); })} className="px-2 py-1 bg-white/10 rounded text-xs">Load Export</button>
                </div>
              </div>
            )}

          </div>
        </div>
      </div>
    </div>
  );
}
*/

