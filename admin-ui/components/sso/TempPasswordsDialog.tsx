"use client";

import { X, Copy, Check, Download, AlertTriangle } from "lucide-react";
import { useState } from "react";

interface TempPassword {
  user_id: string;
  identifier: string;
  email: string | null;
  password?: string;
  expires_at?: string;
}

interface Props {
  isOpen: boolean;
  onClose: () => void;
  passwords: TempPassword[];
  title?: string;
  message?: string;
}

export function TempPasswordsDialog({ isOpen, onClose, passwords, title, message }: Props) {
  const [copied, setCopied] = useState(false);

  if (!isOpen) return null;

  const handleCopy = () => {
    const text = passwords.map(p => `${p.identifier} (${p.email || 'no email'}): ${p.password}`).join("\n");
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const csvContent = "data:text/csv;charset=utf-8," 
      + "Identifier,Email,Password,ExpiresAt\n"
      + passwords.map(e => `${e.identifier},${e.email || ''},${e.password},${e.expires_at || ''}`).join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", "temp_passwords.csv");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl bg-[#121212] border border-white/10 rounded-2xl shadow-2xl flex flex-col max-h-[85vh]">
        <div className="flex items-center justify-between p-6 border-b border-white/5">
          <h3 className="text-xl font-bold text-white">{title || "Password Temporanee"}</h3>
          <button onClick={onClose} className="p-2 hover:bg-white/5 rounded-full transition-colors text-gray-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>
        
        <div className="p-6 overflow-y-auto flex-1">
          {message && (
            <div className="mb-6 p-4 rounded-xl bg-yellow-500/10 border border-yellow-500/20 text-yellow-500 flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
              <div className="text-sm font-medium leading-relaxed">{message}</div>
            </div>
          )}
          
          <div className="space-y-2">
            {passwords.map((p, i) => (
              <div key={i} className="flex flex-col sm:flex-row sm:items-center justify-between p-4 bg-white/5 border border-white/10 rounded-xl gap-4">
                <div className="min-w-0">
                  <div className="font-bold text-white truncate">{p.identifier}</div>
                  {p.email && <div className="text-xs text-gray-500 truncate">{p.email}</div>}
                  {p.expires_at && (
                    <div className="text-[10px] text-gray-600 mt-1">Scade: {new Date(p.expires_at).toLocaleString()}</div>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <code className="px-3 py-1.5 bg-black rounded border border-white/10 text-emerald-400 font-mono text-sm">
                    {p.password}
                  </code>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="p-6 border-t border-white/5 flex flex-col sm:flex-row justify-between items-center gap-4 bg-white/[0.02]">
          <p className="text-xs text-red-400 font-bold max-w-sm">
            Attenzione: queste password vengono mostrate una sola volta. Copiale o scaricale ora.
          </p>
          <div className="flex gap-2 w-full sm:w-auto">
            <button
              onClick={handleCopy}
              className="flex-1 sm:flex-none flex items-center justify-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 text-white rounded-lg transition-colors text-sm font-bold"
            >
              {copied ? <Check className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4" />} Copia Tutti
            </button>
            <button
              onClick={handleDownload}
              className="flex-1 sm:flex-none flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors text-sm font-bold"
            >
              <Download className="w-4 h-4" /> CSV
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
