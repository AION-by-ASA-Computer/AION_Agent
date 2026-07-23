"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { getStoredToken } from "@/lib/auth/storage";
import { MessageSquare, User, Clock, ChevronRight, Search, X, Terminal, Bot, RefreshCw, Paperclip, FileCode, Layers, Download, ThumbsUp, ThumbsDown } from "lucide-react";
import { CustomDatePicker } from "@/components/CustomDatePicker";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Suspense } from "react";

function ConversationsContent() {
  const [convs, setConvs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [selectedConv, setSelectedConv] = useState<any | null>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);

  const searchParams = useSearchParams();
  const preselectedId = searchParams.get("id");
  const preselectedMessageId = searchParams.get("message");

  useEffect(() => {
    if (preselectedId && convs.length > 0) {
      const found = convs.find(c => c.id === preselectedId);
      if (found) {
        handleSelectConv(found);
      }
    }
  }, [preselectedId, convs]);

  useEffect(() => {
    if (preselectedMessageId && messages.length > 0) {
      setTimeout(() => {
        const el = document.getElementById(`message-${preselectedMessageId}`);
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }, 100);
    }
  }, [preselectedMessageId, messages]);

  const fetchConvs = () => {
    setLoading(true);
    apiFetch(`${apiBase()}/admin/conversations/global`)
      .then(res => res.ok ? res.json() : Promise.reject(res))
      .then(data => {
        setConvs(data.conversations || []);
        setLoading(false);
      })
      .catch(err => {
        console.error("Conversations fetch failed", err);
        setConvs([]);
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchConvs();
  }, []);

  const handleStartDateChange = (val: string) => {
    setStartDate(val);
    if (endDate && val > endDate) {
      setEndDate(val);
    }
  };

  const handleEndDateChange = (val: string) => {
    setEndDate(val);
    if (startDate && val < startDate) {
      setStartDate(val);
    }
  };

  const handleSelectConv = (conv: any) => {
    setSelectedConv(conv);
    setLoadingMessages(true);
    apiFetch(`${apiBase()}/admin/conversations/${conv.id}/messages?include_internal=true`)
      .then(res => res.json())
      .then(data => {
        setMessages(data.messages || []);
        setLoadingMessages(false);
      })
      .catch(err => {
        console.error("Failed to fetch messages", err);
        setMessages([]);
        setLoadingMessages(false);
      });
  };

  const filteredConvs = convs.filter(c => {
    const query = searchQuery.toLowerCase();
    const titleMatch = (c.title || "").toLowerCase().includes(query);
    const idMatch = c.id.toLowerCase().includes(query);
    const userMatch = (c.user_id || "").toLowerCase().includes(query);
    const tenantMatch = (c.tenant_id || "").toLowerCase().includes(query);
    const profileMatch = (c.profile_slug || "").toLowerCase().includes(query);
    const textMatch = titleMatch || idMatch || userMatch || tenantMatch || profileMatch;

    let dateMatch = true;
    if (startDate || endDate) {
      const convDate = new Date(c.updated_at);
      if (startDate) {
        const start = new Date(startDate);
        start.setHours(0, 0, 0, 0);
        if (convDate < start) dateMatch = false;
      }
      if (endDate) {
        const end = new Date(endDate);
        end.setHours(23, 59, 59, 999);
        if (convDate > end) dateMatch = false;
      }
    }

    return textMatch && dateMatch;
  });

  return (
    <div className="space-y-8 pb-12">
      {/* Header */}
      <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 p-6">
        <div className="space-y-1">
          <h2 className="text-3xl font-extrabold tracking-tight text-white">Interaction Ledger</h2>
          <p className="text-md text-gray-400 max-w-xl mt-2">
            Cross-tenant monitoring of all AION Agent conversations.
          </p>
        </div>
        <button
          onClick={fetchConvs}
          disabled={loading}
          className="flex items-center gap-2 px-5 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl font-bold text-sm shadow-lg shadow-blue-500/20 transition-all transform active:scale-95 cursor-pointer disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} /> REFRESH LEDGER
        </button>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Conversations List (Left Column) */}
        <div className="lg:col-span-5 xl:col-span-4 flex flex-col h-[78vh] space-y-4">
          <div className="flex items-center justify-between px-1">
            <h3 className="text-xs font-bold uppercase tracking-wider text-gray-400">
              Active Sessions ({filteredConvs.length})
            </h3>
          </div>

          {/* Filters */}
          <div className="space-y-2">
            <div className="relative group">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 group-focus-within:text-blue-400 transition-colors" />
              <input
                type="text"
                placeholder="Search by title, user, tenant..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-black/40 backdrop-blur-sm border border-white/10 rounded-xl pl-10 pr-10 py-3 text-sm text-white placeholder:text-gray-600 focus:border-blue-500/80 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all shadow-inner"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery("")}
                  className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white transition-colors p-1 cursor-pointer"
                >
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>

            <div className="grid grid-cols-2 gap-2">
              <CustomDatePicker
                label="Da data"
                value={startDate}
                maxDate={endDate || undefined}
                onChange={handleStartDateChange}
                placeholder="Inizio"
              />
              <CustomDatePicker
                label="A data"
                value={endDate}
                minDate={startDate || undefined}
                onChange={handleEndDateChange}
                placeholder="Fine"
              />
            </div>
            {(startDate || endDate) && (
              <div className="flex justify-end">
                <button
                  onClick={() => { setStartDate(""); setEndDate(""); }}
                  className="text-[10px] text-blue-400 hover:text-blue-300 font-semibold transition-colors flex items-center gap-1 cursor-pointer"
                >
                  <X className="w-3 h-3" /> Resetta filtro date
                </button>
              </div>
            )}
          </div>

          {/* Sessions Cards */}
          <div className="space-y-3 overflow-y-auto flex-1 min-h-0 pr-1 custom-scrollbar">
            {loading && convs.length === 0 ? (
              <div className="py-12 text-center text-gray-500 animate-pulse text-sm">
                Loading interaction records...
              </div>
            ) : filteredConvs.map((c) => {
              const isSelected = selectedConv?.id === c.id;

              return (
                <div
                  key={c.id}
                  onClick={() => handleSelectConv(c)}
                  className={`group relative p-4 rounded-2xl border backdrop-blur-sm cursor-pointer transition-all duration-200 flex items-center justify-between ${isSelected
                    ? "bg-gradient-to-r from-blue-600/15 to-indigo-600/5 border-blue-500/50 shadow-lg shadow-blue-500/10 translate-x-1"
                    : "bg-[#121212]/80 border-white/5 hover:border-white/15 hover:bg-[#181818]"
                    }`}
                >
                  {isSelected && (
                    <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-8 bg-blue-500 rounded-r-full shadow-[0_0_8px_#3b82f6]" />
                  )}

                  <div className="flex items-center gap-4 min-w-0 pr-4 flex-1">
                    <div className="p-2.5 bg-blue-500/10 border border-blue-500/20 rounded-xl text-blue-400 shrink-0">
                      <MessageSquare className="w-5 h-5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="font-bold text-base text-white truncate flex items-center gap-2">
                        {c.title || 'Untitled Session'}
                      </div>
                      <div className="flex items-center gap-2 text-xs text-gray-400 truncate mt-1">
                        <span className="flex items-center gap-1"><User className="w-3 h-3 text-gray-500 shrink-0" /> <span className="truncate">{c.user_id}</span></span>
                        <span>•</span>
                        <span className="uppercase text-[10px] font-bold text-gray-500 shrink-0">{c.tenant_id}</span>
                      </div>
                      <div className="flex items-center gap-2 mt-2">
                        <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-[#141414] text-gray-400 border border-[#262626] uppercase shrink-0">
                          {c.profile_slug}
                        </span>
                        <span className="text-[10px] text-gray-500 ml-auto flex items-center gap-1 shrink-0">
                          <Clock className="w-3 h-3" /> {new Date(c.updated_at).toLocaleDateString()}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0 ml-2">
                    <span className="text-xs font-bold text-blue-400 bg-blue-500/10 px-2 py-1 rounded-lg border border-blue-500/20">
                      {c.message_count}
                    </span>
                    <ChevronRight
                      className={`w-4 h-4 transition-transform ${isSelected
                        ? "text-blue-400 translate-x-0.5"
                        : "text-gray-600 group-hover:text-gray-400"
                        }`}
                    />
                  </div>
                </div>
              );
            })}

            {filteredConvs.length === 0 && !loading && (
              <div className="flex flex-col items-center justify-center text-center py-12 px-4 bg-[#121212]/50 border border-white/5 rounded-2xl">
                <Search className="w-8 h-8 text-gray-600 mb-2" />
                <p className="text-sm font-semibold text-gray-400">No sessions found</p>
                <p className="text-xs text-gray-600 mt-1 max-w-xs">
                  Try adjusting your search query or refresh the ledger.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Audit Log / Detail Area (Right Column) */}
        <div className="lg:col-span-7 xl:col-span-8 flex flex-col h-[78vh]">
          {selectedConv ? (
            <div className="glass-card flex-1 flex flex-col p-6 sm:p-8 border border-white/10 rounded-3xl bg-gradient-to-b from-[#181818]/90 to-[#121212]/90 shadow-2xl relative overflow-hidden">
              <div className="absolute top-0 right-0 w-64 h-64 bg-blue-500/5 rounded-full blur-3xl pointer-events-none" />

              {/* Header */}
              <div className="flex justify-between items-center pb-5 border-b border-white/10 shrink-0 mb-6">
                <div className="flex items-center gap-4 min-w-0 pr-4">
                  <div className="p-2.5 bg-blue-500/10 border border-blue-500/20 rounded-xl text-blue-400 shrink-0">
                    <MessageSquare className="w-6 h-6" />
                  </div>
                  <div className="min-w-0">
                    <h3 className="text-xl font-bold text-white truncate font-mono">
                      {selectedConv.title || 'Untitled Session'}
                    </h3>
                    <div className="flex items-center gap-3 text-xs text-gray-400 mt-1">
                      <span className="font-mono text-[10px] bg-black/40 px-2 py-0.5 rounded border border-white/5 truncate max-w-[200px]">{selectedConv.id}</span>
                      <span>•</span>
                      <span className="text-blue-400 font-semibold uppercase tracking-wider text-[10px] shrink-0">{selectedConv.profile_slug}</span>
                    </div>
                  </div>
                </div>
                <button
                  onClick={() => setSelectedConv(null)}
                  className="p-2 text-gray-500 hover:text-white hover:bg-white/5 rounded-xl transition-colors cursor-pointer shrink-0"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Metadata row */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 bg-black/30 p-4 rounded-2xl border border-white/5 shrink-0 mb-6">
                <div className="min-w-0">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Identity</div>
                  <div className="text-sm font-semibold text-gray-200 mt-1 flex items-center gap-1.5 truncate">
                    <User className="w-3.5 h-3.5 text-blue-400 shrink-0" />
                    <span className="truncate">{selectedConv.user_id}</span>
                  </div>
                </div>
                <div className="min-w-0">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Tenant</div>
                  <div className="text-sm font-semibold text-gray-200 mt-1 uppercase font-mono truncate">{selectedConv.tenant_id}</div>
                </div>
                <div className="min-w-0">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Last Activity</div>
                  <div className="text-sm font-semibold text-gray-200 mt-1 flex items-center gap-1.5 truncate">
                    <Clock className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                    <span className="truncate">{new Date(selectedConv.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                </div>
                <div className="min-w-0">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Messages</div>
                  <div className="text-sm font-semibold text-blue-400 mt-1">{selectedConv.message_count} messages</div>
                </div>
              </div>

              {/* Messages Audit Log */}
              <div className="flex-1 min-h-0 overflow-y-auto pr-2 custom-scrollbar space-y-4 pb-4">
                {loadingMessages ? (
                  <div className="py-20 text-center text-gray-500 flex flex-col items-center gap-3">
                    <RefreshCw className="w-6 h-6 animate-spin text-blue-500" />
                    <span className="text-xs font-semibold">Loading audit trail...</span>
                  </div>
                ) : messages.length === 0 ? (
                  <div className="py-20 text-center text-gray-600 italic text-sm">No messages recorded in this session.</div>
                ) : (
                  messages.map((m) => {
                    const isHighlighted = m.id === preselectedMessageId;
                    return (
                      <div
                        key={m.id}
                        id={`message-${m.id}`}
                        className={`flex gap-4 p-4 rounded-2xl transition-all duration-300 ${
                          isHighlighted
                            ? "bg-blue-500/10 border-2 border-blue-500 shadow-[0_0_15px_rgba(59,130,246,0.3)] ring-2 ring-blue-500/20"
                            : m.role === "user"
                              ? "bg-white/[0.02] border border-white/5"
                              : m.tool_name
                                ? "bg-amber-500/[0.02] border border-amber-500/10"
                                : "bg-blue-500/[0.04] border border-blue-500/10"
                        }`}
                      >
                      <div className={`w-8 h-8 rounded-xl flex items-center justify-center border shrink-0 ${m.role === 'user'
                        ? 'bg-gray-500/10 border-gray-500/20 text-gray-400'
                        : m.tool_name
                          ? 'bg-amber-500/10 border-amber-500/20 text-amber-500'
                          : 'bg-blue-500/10 border-blue-500/20 text-blue-400'
                        }`}>
                        {m.role === 'user' ? <User className="w-4 h-4" /> : m.tool_name ? <Terminal className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
                      </div>
                      <div className="space-y-1.5 flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2">
                          <span className={`text-[10px] font-bold uppercase tracking-widest ${m.role === 'user' ? 'text-gray-400' : m.tool_name ? 'text-amber-500' : 'text-blue-400'
                            } flex items-center gap-1.5`}>
                            {m.role === 'user' ? 'Human' : m.tool_name ? `Tool: ${m.tool_name}` : 'AION Agent'}
                            {m.rating === 1 && (
                              <span className="flex items-center gap-1 text-[10px] font-bold text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-full lowercase tracking-normal normal-case">
                                <ThumbsUp className="w-3 h-3 text-emerald-400 shrink-0" /> liked
                              </span>
                            )}
                            {m.rating === -1 && (
                              <span className="flex items-center gap-1 text-[10px] font-bold text-rose-400 bg-rose-500/10 border border-rose-500/20 px-2 py-0.5 rounded-full lowercase tracking-normal normal-case">
                                <ThumbsDown className="w-3 h-3 text-rose-400 shrink-0" /> disliked
                              </span>
                            )}
                          </span>
                          <span className="text-[9px] font-mono text-gray-600">#{m.seq}</span>
                        </div>
                        <div className={`text-sm leading-relaxed break-words prose prose-invert max-w-none prose-sm prose-p:leading-relaxed prose-pre:bg-black/50 prose-pre:border prose-pre:border-white/5 prose-table:border prose-table:border-white/10 prose-th:bg-white/5 prose-th:p-2 prose-td:p-2 prose-td:border-b prose-td:border-white/5 ${m.role === 'user' ? 'text-gray-300' : 'text-white font-medium'}`}>
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {m.content?.trim() || ""}
                          </ReactMarkdown>
                        </div>

                        {/* Steps (Tool Calls) */}
                        {m.steps && m.steps.length > 0 && (
                          <div className="mt-3 space-y-1.5 pt-2 border-t border-white/5">
                            <div className="text-[10px] font-bold uppercase tracking-wider text-gray-500 flex items-center gap-1">
                              <Terminal className="w-3 h-3 text-amber-500" /> Tool Execution Steps ({m.steps.length})
                            </div>
                            <div className="grid grid-cols-1 gap-1.5">
                              {m.steps.map((s: any) => (
                                <div key={s.id} className="bg-black/30 border border-white/5 rounded-xl p-2.5 text-xs font-mono space-y-1">
                                  <div className="flex items-center justify-between text-amber-400 font-bold">
                                    <span>{s.name}</span>
                                    {s.is_error ? <span className="text-red-400 font-sans text-[10px] bg-red-500/10 px-1.5 py-0.5 rounded border border-red-500/20">ERROR</span> : <span className="text-green-400 font-sans text-[10px] bg-green-500/10 px-1.5 py-0.5 rounded border border-green-500/20">SUCCESS</span>}
                                  </div>
                                  {s.input && (
                                    <div className="text-gray-400 text-[11px] truncate">Input: {s.input}</div>
                                  )}
                                  {s.output && (
                                    <div className="text-gray-300 text-[11px] bg-black/40 p-1.5 rounded border border-white/5 max-h-32 overflow-y-auto custom-scrollbar whitespace-pre-wrap font-mono">
                                      {s.output}
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Plan Artifact */}
                        {(() => {
                          const planArt = m.artifacts?.find((a: any) => a.kind === 'plan' || (a.original_name || '').toLowerCase().includes('execution_plan'));
                          if (!planArt) return null;
                          const token = getStoredToken();
                          const downloadUrl = planArt.storage_key ? `${apiBase()}/sessions/${encodeURIComponent(selectedConv.id)}/download?relative_path=${encodeURIComponent(planArt.storage_key)}${token ? `&access_token=${encodeURIComponent(token)}` : ''}` : undefined;
                          return (
                            <div className="mt-3 pt-2 border-t border-white/5">
                              <div className="bg-blue-500/10 border border-blue-500/20 rounded-2xl p-3 space-y-2">
                                <div className="flex items-center justify-between gap-2">
                                  <div className="flex items-center gap-2 text-blue-400 font-bold text-xs">
                                    <Layers className="w-4 h-4" /> AION Execution Plan
                                  </div>
                                  {downloadUrl && (
                                    <a
                                      href={downloadUrl}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="flex items-center gap-1.5 px-2.5 py-1 bg-blue-500/20 hover:bg-blue-500/30 text-blue-300 hover:text-white rounded-lg text-xs font-semibold transition-colors border border-blue-500/30 shadow-sm"
                                    >
                                      <Download className="w-3.5 h-3.5" /> Download
                                    </a>
                                  )}
                                </div>
                                <div className="text-xs text-gray-300 font-mono bg-black/40 p-2.5 rounded-xl border border-white/5 max-h-48 overflow-y-auto custom-scrollbar whitespace-pre-wrap">
                                  {planArt.content || `[Plan File: ${planArt.original_name || planArt.storage_key}]`}
                                </div>
                              </div>
                            </div>
                          );
                        })()}

                        {/* General Artifacts & Attachments */}
                        {(() => {
                          const genArts = m.artifacts?.filter((a: any) => a.kind !== 'plan' && !(a.original_name || '').toLowerCase().includes('execution_plan'));
                          if (!genArts || genArts.length === 0) return null;
                          const token = getStoredToken();
                          return (
                            <div className="mt-3 pt-2 border-t border-white/5">
                              <div className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-2 flex items-center gap-1">
                                <Paperclip className="w-3 h-3 text-blue-400" /> {m.role === 'user' ? 'Allegati Utente' : 'Artefatti Generati'} ({genArts.length})
                              </div>
                              <div className="flex flex-wrap gap-2">
                                {genArts.map((a: any) => {
                                  const downloadUrl = a.storage_key ? `${apiBase()}/sessions/${encodeURIComponent(selectedConv.id)}/download?relative_path=${encodeURIComponent(a.storage_key)}${token ? `&access_token=${encodeURIComponent(token)}` : ''}` : undefined;
                                  return (
                                    <div key={a.id} className="flex items-center gap-2 bg-white/5 border border-white/10 rounded-xl pl-3 pr-1.5 py-1.5 text-xs text-gray-200 shadow-sm">
                                      <FileCode className="w-3.5 h-3.5 text-blue-400" />
                                      <span className="font-mono font-semibold truncate max-w-[200px]">{a.original_name || a.storage_key || a.id}</span>
                                      {a.size_bytes && <span className="text-[10px] text-gray-500">({Math.round(a.size_bytes / 1024)}KB)</span>}
                                      {downloadUrl && (
                                        <a
                                          href={downloadUrl}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          className="p-1 text-gray-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors ml-1"
                                          title="Download file"
                                        >
                                          <Download className="w-3.5 h-3.5" />
                                        </a>
                                      )}
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          );
                        })()}
                      </div>
                    </div>
                  );
                })
                )}
              </div>
            </div>
          ) : (
            <div className="glass-card flex-1 flex flex-col items-center justify-center text-center p-12 space-y-6 border border-white/5 rounded-3xl min-h-[450px]">
              <div className="w-20 h-20 rounded-2xl bg-gradient-to-tr from-blue-500/10 to-indigo-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 shadow-xl shadow-blue-500/5">
                <MessageSquare className="w-10 h-10" />
              </div>
              <div className="space-y-2 max-w-sm">
                <h3 className="text-xl font-bold text-white">Select an Audit Session</h3>
                <p className="text-sm text-gray-400 leading-relaxed">
                  Choose a conversation session from the list on the left to inspect real-time interaction logs, human prompts, tool calls, and agent responses.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function GlobalConversations() {
  return (
    <Suspense fallback={<div className="py-20 text-center text-gray-500 animate-pulse">Loading conversations ledger...</div>}>
      <ConversationsContent />
    </Suspense>
  );
}

