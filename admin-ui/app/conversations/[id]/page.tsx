"use client";

import { useEffect, useState, use } from "react";
import { apiFetch } from "@/lib/api/headers"
import { useRouter } from "next/navigation";
import { apiBase } from "@/lib/api";
import { ChevronLeft, MessageSquare, User, Clock, Terminal, Bot } from "lucide-react";

export default function ConversationDetails({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [messages, setMessages] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    apiFetch(`${apiBase()}/admin/conversations/${id}/messages?include_internal=true`)
      .then(res => res.json())
      .then(data => {
        setMessages(data.messages || []);
        setLoading(false);
      })
      .catch(err => {
        console.error("Failed to fetch messages", err);
        setLoading(false);
      });
  }, [id]);

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <button 
        onClick={() => router.back()}
        className="flex items-center gap-2 text-gray-500 hover:text-white transition-colors text-xs font-bold uppercase tracking-wider"
      >
        <ChevronLeft className="w-4 h-4" /> Back to Ledger
      </button>

      <div className="glass-card p-6 border-[#262626]">
        <div className="flex items-center gap-4 mb-8 pb-6 border-b border-[#262626]">
          <div className="w-12 h-12 rounded-2xl bg-purple-500/10 flex items-center justify-center border border-purple-500/20">
            <MessageSquare className="w-6 h-6 text-purple-500" />
          </div>
          <div>
            <h2 className="text-xl font-bold">Audit Session: {id.slice(0, 8)}...</h2>
            <div className="flex items-center gap-4 mt-1 text-[10px] text-gray-500 font-bold uppercase">
              <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> Real-time Audit</span>
              <span className="flex items-center gap-1 text-purple-500">AION V2 Protocol</span>
            </div>
          </div>
        </div>

        <div className="space-y-8">
          {loading ? (
            <div className="py-20 text-center text-gray-500 animate-pulse">Loading conversation history...</div>
          ) : (
            messages.map((m) => (
              <div key={m.id} className={`flex gap-4 ${m.role === 'user' ? 'opacity-80' : ''}`}>
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center border shrink-0 ${
                  m.role === 'user' 
                    ? 'bg-gray-500/10 border-gray-500/20 text-gray-400' 
                    : m.tool_name 
                      ? 'bg-amber-500/10 border-amber-500/20 text-amber-500'
                      : 'bg-blue-500/10 border-blue-500/20 text-blue-500'
                }`}>
                  {m.role === 'user' ? <User className="w-4 h-4" /> : m.tool_name ? <Terminal className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
                </div>
                <div className="space-y-1 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-bold uppercase tracking-widest text-gray-500">
                      {m.role === 'user' ? 'Human' : m.tool_name ? `Tool: ${m.tool_name}` : 'AION Agent'}
                    </span>
                    <span className="text-[9px] text-gray-700">#{m.seq}</span>
                  </div>
                  <div className={`text-sm leading-relaxed ${m.role === 'user' ? 'text-gray-300' : 'text-white'}`}>
                    {m.content.split('\n').map((line: string, i: number) => (
                      <p key={i} className={line ? 'mb-2' : 'h-2'}>{line}</p>
                    ))}
                  </div>
                </div>
              </div>
            ))
          )}
          {!loading && messages.length === 0 && (
            <div className="py-20 text-center text-gray-600 italic">No messages found for this session.</div>
          )}
        </div>
      </div>
    </div>
  );
}
