"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { 
  ThumbsUp, 
  ThumbsDown, 
  User, 
  Clock, 
  ExternalLink, 
  MessageSquare, 
  RefreshCw,
  Cpu,
  Layers,
  Trash2
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import Link from "next/link";

export default function FeedbackDashboard() {
  const [feedbacks, setFeedbacks] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"liked" | "disliked">("liked");
  const [dismissingIds, setDismissingIds] = useState<Set<string>>(new Set());

  const handleDismiss = async (messageId: string) => {
    if (dismissingIds.has(messageId)) return;
    setDismissingIds((prev) => {
      const next = new Set(prev);
      next.add(messageId);
      return next;
    });
    try {
      const res = await apiFetch(`${apiBase()}/admin/feedback/${messageId}`, {
        method: "DELETE",
      });
      if (res.ok) {
        setFeedbacks((prev) => prev.filter((f) => f.message_id !== messageId));
      } else {
        console.error("Failed to dismiss feedback:", res.statusText);
        alert("Failed to dismiss feedback");
      }
    } catch (err) {
      console.error("Error dismissing feedback:", err);
      alert("Error dismissing feedback");
    } finally {
      setDismissingIds((prev) => {
        const next = new Set(prev);
        next.delete(messageId);
        return next;
      });
    }
  };

  const fetchFeedback = () => {
    setLoading(true);
    apiFetch(`${apiBase()}/admin/feedback`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data) => {
        setFeedbacks(data.feedback || []);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Feedback fetch failed", err);
        setFeedbacks([]);
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchFeedback();
  }, []);

  const filteredFeedbacks = feedbacks.filter((f) => 
    activeTab === "liked" ? f.rating === 1 : f.rating === -1
  );

  return (
    <div className="space-y-8 pb-12">
      {/* Header */}
      <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 p-6 bg-[#121212]/30 border border-white/5 rounded-3xl backdrop-blur-md">
        <div className="space-y-1">
          <h2 className="text-3xl font-extrabold tracking-tight text-white flex items-center gap-2">
            <MessageSquare className="w-8 h-8 text-blue-500" />
            User Feedback Ledger
          </h2>
          <p className="text-md text-gray-400 max-w-xl">
            Monitor thumbs-up/thumbs-down signals and detailed reviews from users.
          </p>
        </div>
        <button
          onClick={fetchFeedback}
          disabled={loading}
          className="flex items-center gap-2 px-5 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl font-bold text-sm shadow-lg shadow-blue-500/20 transition-all transform active:scale-95 cursor-pointer disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} /> REFRESH FEEDBACK
        </button>
      </header>

      {/* Tabs */}
      <div className="flex border-b border-white/10 pb-px">
        <button
          onClick={() => setActiveTab("liked")}
          className={`flex items-center gap-2 px-6 py-3.5 border-b-2 font-bold text-sm transition-all cursor-pointer ${
            activeTab === "liked"
              ? "border-emerald-500 text-emerald-400 bg-emerald-500/5"
              : "border-transparent text-gray-400 hover:text-white"
          }`}
        >
          <ThumbsUp className="w-4 h-4" />
          Liked Messages ({feedbacks.filter(f => f.rating === 1).length})
        </button>
        <button
          onClick={() => setActiveTab("disliked")}
          className={`flex items-center gap-2 px-6 py-3.5 border-b-2 font-bold text-sm transition-all cursor-pointer ${
            activeTab === "disliked"
              ? "border-rose-500 text-rose-400 bg-rose-500/5"
              : "border-transparent text-gray-400 hover:text-white"
          }`}
        >
          <ThumbsDown className="w-4 h-4" />
          Disliked Messages ({feedbacks.filter(f => f.rating === -1).length})
        </button>
      </div>

      {/* Content */}
      <div className="space-y-6">
        {loading ? (
          <div className="py-20 text-center text-gray-500 flex flex-col items-center gap-3">
            <RefreshCw className="w-8 h-8 animate-spin text-blue-500" />
            <span className="text-sm font-semibold">Loading user evaluations...</span>
          </div>
        ) : filteredFeedbacks.length === 0 ? (
          <div className="py-20 text-center text-gray-500 border border-dashed border-white/10 rounded-3xl bg-[#121212]/10">
            <MessageSquare className="w-12 h-12 text-gray-600 mx-auto mb-4" />
            <p className="text-base text-gray-400 font-medium">No feedback recorded under this category.</p>
          </div>
        ) : (
          filteredFeedbacks.map((f) => (
            <div 
              key={f.message_id} 
              className={`p-6 rounded-3xl border backdrop-blur-sm transition-all hover:bg-[#121212]/50 ${
                activeTab === "liked"
                  ? "bg-[#121212]/30 border-emerald-500/10 hover:border-emerald-500/20"
                  : "bg-[#121212]/30 border-rose-500/10 hover:border-rose-500/20"
              }`}
            >
              {/* Card Meta & Header */}
              <div className="flex flex-wrap items-center justify-between gap-4 mb-6 pb-4 border-b border-white/5">
                <div className="flex flex-wrap items-center gap-3 text-xs">
                  <span className="flex items-center gap-1.5 px-3 py-1 bg-white/5 border border-white/10 rounded-full text-gray-300">
                    <User className="w-3.5 h-3.5 text-gray-400" />
                    <span className="font-semibold">{f.user_id}</span>
                  </span>
                  {f.tenant_id && (
                    <span className="text-[10px] uppercase font-bold text-gray-500 bg-white/5 border border-white/10 px-2 py-1 rounded-full">
                      Tenant: {f.tenant_id}
                    </span>
                  )}
                  <span className="flex items-center gap-1.5 px-3 py-1 bg-[#181818] border border-[#282828] rounded-full text-gray-400">
                    <Layers className="w-3.5 h-3.5 text-gray-500" />
                    Profile: <span className="text-white font-semibold">{f.profile_name}</span>
                  </span>
                  <span className="flex items-center gap-1 text-gray-500">
                    <Clock className="w-3.5 h-3.5" />
                    {new Date(f.created_at).toLocaleString()}
                  </span>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <Link
                    href={`/conversations?id=${f.conversation_id}&message=${f.message_id}`}
                    className="flex items-center gap-1.5 px-4 py-2 bg-blue-500/10 border border-blue-500/20 hover:bg-blue-500/20 text-blue-400 rounded-xl font-bold text-xs transition-all"
                  >
                    VIEW FULL CHAT
                    <ExternalLink className="w-3.5 h-3.5" />
                  </Link>
                  <button
                    onClick={() => handleDismiss(f.message_id)}
                    disabled={dismissingIds.has(f.message_id)}
                    className="flex items-center gap-1.5 px-4 py-2 bg-rose-500/10 border border-rose-500/20 hover:bg-rose-500/20 text-rose-400 rounded-xl font-bold text-xs transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    DISMISS
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {/* QA Columns/Stack */}
              <div className="space-y-4">
                {/* User Prompt */}
                {f.prompt && (
                  <div className="bg-white/[0.01] border border-white/5 rounded-2xl p-4">
                    <div className="text-[10px] font-extrabold uppercase tracking-wider text-gray-500 mb-2">
                      User Prompt
                    </div>
                    <div className="text-sm text-gray-300 leading-relaxed font-medium">
                      {f.prompt.content}
                    </div>
                  </div>
                )}

                {/* Agent Response */}
                <div className="bg-blue-500/[0.01] border border-blue-500/5 rounded-2xl p-4">
                  <div className="text-[10px] font-extrabold uppercase tracking-wider text-blue-400 mb-2 flex items-center gap-1">
                    <Cpu className="w-3.5 h-3.5" />
                    Agent Response
                  </div>
                  <div className="text-sm text-white font-medium prose prose-invert prose-sm max-w-none prose-p:leading-relaxed prose-pre:bg-black/50 prose-pre:border prose-pre:border-white/5 prose-table:border prose-table:border-white/10 prose-th:bg-white/5 prose-th:p-2 prose-td:p-2 prose-td:border-b prose-td:border-white/5 leading-relaxed">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {f.content}
                    </ReactMarkdown>
                  </div>
                </div>

                {/* Dislike Explanation Comment */}
                {f.rating === -1 && f.feedback_comment && (
                  <div className="bg-rose-500/5 border border-rose-500/10 rounded-2xl p-4">
                    <div className="text-[10px] font-extrabold uppercase tracking-wider text-rose-400 mb-2">
                      User Explanation
                    </div>
                    <div className="text-sm text-rose-200 leading-relaxed font-semibold italic">
                      &ldquo;{f.feedback_comment}&rdquo;
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
