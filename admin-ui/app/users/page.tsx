"use client";

import { useState, useEffect } from "react";
import { Users, Plus, Trash2, Edit2, Key, CheckCircle, Save, X, AlertTriangle } from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { PageToast, ToastState } from "@/components/PageToast";

export default function UsersPage() {
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingUserId, setEditingUserId] = useState<string | null>(null);

  // Form state
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");

  const [toast, setToast] = useState<ToastState>(null);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [userToDelete, setUserToDelete] = useState<any>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    fetchUsers();
  }, []);

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/users`);
      if (!res.ok) throw new Error("Failed to fetch users");
      const data = await res.json();
      setUsers(data.users || []);
    } catch (err: any) {
      setToast({ message: "Impossibile caricare gli utenti: " + err.message, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  const openAddForm = () => {
    setEditingUserId(null);
    setIdentifier("");
    setDisplayName("");
    setEmail("");
    setPassword("");
    setShowForm(true);
  };

  const openEditForm = (user: any) => {
    setEditingUserId(user.id);
    setIdentifier(user.identifier);
    setDisplayName(user.display_name || "");
    setEmail(user.email || "");
    setPassword(""); // Don't fetch password hash
    setShowForm(true);
  };

  const closeForm = () => {
    setShowForm(false);
    setEditingUserId(null);
  };

  const saveUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const isEdit = editingUserId !== null;
      const url = isEdit 
        ? `${apiBase()}/admin/users/${editingUserId}` 
        : `${apiBase()}/admin/users`;
      
      const method = isEdit ? "PUT" : "POST";
      
      const payload: any = {
        display_name: displayName,
        email: email
      };

      if (!isEdit) {
        if (!identifier || !password) {
          throw new Error("Username and Password are required for new users");
        }
        payload.identifier = identifier;
        payload.password = password;
      } else {
        if (password) {
          payload.password = password;
        }
      }

      const res = await apiFetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Failed to save user");
      }

      closeForm();
      fetchUsers();
      setToast({ message: isEdit ? "Utente aggiornato con successo!" : "Utente creato con successo!", variant: "success" });
    } catch (err: any) {
      setToast({ message: err.message, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteClick = (user: any) => {
    setUserToDelete(user);
    setIsDeleteModalOpen(true);
  };

  const executeDelete = async (id: string) => {
    setDeleting(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/users/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to delete user");
      setToast({ message: "Utente eliminato con successo.", variant: "success" });
      setIsDeleteModalOpen(false);
      setUserToDelete(null);
      fetchUsers();
    } catch (err: any) {
      setToast({ message: "Errore durante l'eliminazione dell'utente: " + err.message, variant: "error" });
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-8 pb-12">
      {/* Header */}
      <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 p-6">
        <div className="space-y-1">
          <h2 className="text-3xl font-extrabold tracking-tight text-white">User Management</h2>
          <p className="text-md text-gray-400 max-w-xl mt-2">
            Manage user accounts, authentication credentials, and system access permissions.
          </p>
        </div>
        <button
          onClick={openAddForm}
          className="flex items-center gap-2 px-5 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl font-bold text-sm shadow-lg shadow-blue-500/20 transition-all transform active:scale-95 cursor-pointer"
        >
          <Plus className="w-4 h-4" /> ADD NEW USER
        </button>
      </header>

      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#1a1a1a] border border-white/10 rounded-3xl w-full max-w-2xl overflow-hidden shadow-2xl animate-in zoom-in-95 duration-200 flex flex-col max-h-[90vh]">
            <div className="p-6 border-b border-white/10 flex justify-between items-center bg-white/5 shrink-0">
              <div className="flex items-center gap-3">
                <div className="p-2.5 bg-blue-500/10 border border-blue-500/20 rounded-xl text-blue-400">
                  <Users className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-xl font-bold text-white">
                    {editingUserId ? "Edit User Account" : "Create New User Account"}
                  </h3>
                  <p className="text-xs text-gray-400">
                    {editingUserId ? "Update user profile and authentication details" : "Specify user credentials and profile details"}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={closeForm}
                className="p-2 text-gray-500 hover:text-white hover:bg-white/5 rounded-xl transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={saveUser} className="flex flex-col flex-1 overflow-hidden">
              <div className="p-6 space-y-6 overflow-y-auto custom-scrollbar flex-1">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <label className="text-xs font-bold uppercase tracking-wider text-gray-400 flex items-center justify-between">
                      <span>Username (Login)</span>
                      <span className="text-[10px] text-gray-600 lowercase font-mono">required</span>
                    </label>
                    <input
                      autoFocus
                      disabled={!!editingUserId}
                      className="w-full bg-black/40 border border-white/10 rounded-xl p-3.5 text-sm text-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all shadow-inner font-semibold disabled:opacity-50"
                      placeholder="e.g. admin, mario.rossi"
                      value={identifier}
                      onChange={e => setIdentifier(e.target.value)}
                      required={!editingUserId}
                    />
                  </div>

                  <div className="space-y-2">
                    <label className="text-xs font-bold uppercase tracking-wider text-gray-400 flex items-center justify-between">
                      <span>Password</span>
                      <span className="text-[10px] text-gray-600 lowercase font-mono">
                        {editingUserId ? "leave blank to keep unchanged" : "required"}
                      </span>
                    </label>
                    <input
                      type="password"
                      className="w-full bg-black/40 border border-white/10 rounded-xl p-3.5 text-sm text-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all shadow-inner font-semibold"
                      placeholder="••••••••"
                      value={password}
                      onChange={e => setPassword(e.target.value)}
                      required={!editingUserId}
                    />
                  </div>

                  <div className="space-y-2">
                    <label className="text-xs font-bold uppercase tracking-wider text-gray-400 flex items-center justify-between">
                      <span>Display Name</span>
                      <span className="text-[10px] text-gray-600 lowercase font-mono">optional</span>
                    </label>
                    <input
                      className="w-full bg-black/40 border border-white/10 rounded-xl p-3.5 text-sm text-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all shadow-inner font-semibold"
                      placeholder="e.g. Mario Rossi"
                      value={displayName}
                      onChange={e => setDisplayName(e.target.value)}
                    />
                  </div>

                  <div className="space-y-2">
                    <label className="text-xs font-bold uppercase tracking-wider text-gray-400 flex items-center justify-between">
                      <span>Email</span>
                      <span className="text-[10px] text-gray-600 lowercase font-mono">optional</span>
                    </label>
                    <input
                      type="email"
                      className="w-full bg-black/40 border border-white/10 rounded-xl p-3.5 text-sm text-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all shadow-inner font-semibold"
                      placeholder="e.g. mario@example.com"
                      value={email}
                      onChange={e => setEmail(e.target.value)}
                    />
                  </div>
                </div>
              </div>

              <div className="p-6 border-t border-white/10 flex justify-end gap-3 bg-black/20 shrink-0">
                <button
                  type="button"
                  onClick={closeForm}
                  className="px-5 py-2.5 bg-white/5 hover:bg-white/10 text-gray-300 hover:text-white border border-white/10 rounded-xl text-sm font-semibold transition-all cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="px-6 py-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl font-bold text-sm transition-all shadow-lg shadow-blue-500/20 cursor-pointer transform active:scale-98 disabled:opacity-50 flex items-center gap-2"
                >
                  <Save className="w-4 h-4" /> {editingUserId ? "UPDATE USER" : "CREATE USER"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <div className="glass-card overflow-hidden border border-white/10 rounded-3xl bg-gradient-to-b from-[#181818]/90 to-[#121212]/90 shadow-2xl relative">
        <table className="w-full text-left">
          <thead>
            <tr className="bg-black/40 border-b border-white/10">
              <th className="px-6 py-4 text-xs uppercase font-bold text-gray-400 tracking-wider">User</th>
              <th className="px-6 py-4 text-xs uppercase font-bold text-gray-400 tracking-wider">Email</th>
              <th className="px-6 py-4 text-xs uppercase font-bold text-gray-400 tracking-wider">Tenant</th>
              <th className="px-6 py-4 text-xs uppercase font-bold text-gray-400 tracking-wider text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {users.map((u) => (
              <tr key={u.id} className="hover:bg-white/[0.02] transition-colors group">
                <td className="px-6 py-4">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-blue-500/10 flex items-center justify-center border border-blue-500/20 text-blue-400 font-bold uppercase text-sm shadow-inner shrink-0">
                      {(u.display_name || u.identifier).charAt(0)}
                    </div>
                    <div>
                      <div className="text-sm font-bold text-white">{u.display_name || u.identifier}</div>
                      <div className="text-xs text-gray-500 font-mono mt-0.5">{u.identifier}</div>
                    </div>
                  </div>
                </td>
                <td className="px-6 py-4 text-sm font-semibold text-gray-300">
                  {u.email || <span className="text-gray-600 italic">-</span>}
                </td>
                <td className="px-6 py-4">
                  <span className="text-xs font-mono font-bold px-2.5 py-1 rounded-lg bg-blue-500/10 text-blue-400 border border-blue-500/20 uppercase tracking-wider shadow-sm">
                    {u.tenant_id || "default"}
                  </span>
                </td>
                <td className="px-6 py-4 text-right space-x-2">
                  <button
                    onClick={() => openEditForm(u)}
                    title="Edit User"
                    className="p-2.5 bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 border border-blue-500/20 rounded-xl transition-all hover:border-blue-500/40 cursor-pointer inline-flex items-center justify-center mr-2"
                  >
                    <Edit2 className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => handleDeleteClick(u)}
                    title="Delete User"
                    className="p-2.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 rounded-xl transition-all hover:border-red-500/40 cursor-pointer inline-flex items-center justify-center"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {users.length === 0 && !loading && (
          <div className="p-12 text-center flex flex-col items-center justify-center space-y-3">
            <Users className="w-10 h-10 text-gray-600" />
            <p className="text-sm font-semibold text-gray-400">No active users found</p>
            <p className="text-xs text-gray-600 max-w-sm">Create a new user account above to enable access to the platform.</p>
          </div>
        )}
      </div>

      {isDeleteModalOpen && userToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#1a1a1a] border border-white/10 rounded-2xl w-full max-w-xl overflow-hidden shadow-2xl animate-in zoom-in-95 duration-200">
            <div className="p-6 border-b border-white/10 flex justify-between items-center bg-white/5">
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                <Trash2 className="w-5 h-5 text-red-400" />
                Conferma Eliminazione Utente
              </h2>
              <button
                onClick={() => setIsDeleteModalOpen(false)}
                className="text-gray-500 hover:text-white transition-colors cursor-pointer"
              >
                <X className="w-6 h-6" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-red-300 text-sm leading-relaxed">
                <p className="font-semibold mb-1 text-lg flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5 text-red-400 shrink-0" />
                  <span className="text-white font-bold">ATTENZIONE: operazione irreversibile</span>
                </p>
                Stai per eliminare definitivamente l'utente <b className="text-white font-mono">{userToDelete.identifier}</b> {userToDelete.display_name ? `(${userToDelete.display_name})` : ""}. L'utente non potrà più accedere alla piattaforma.
              </div>
            </div>

            <div className="p-6 border-t border-white/10 flex justify-end gap-3 bg-black/20">
              <button
                onClick={() => setIsDeleteModalOpen(false)}
                className="px-5 py-2.5 text-sm font-semibold text-gray-400 hover:text-white transition-colors cursor-pointer"
              >
                Annulla
              </button>
              <button
                onClick={() => executeDelete(userToDelete.id)}
                disabled={deleting}
                className="bg-red-600 hover:bg-red-500 text-white px-6 py-2.5 rounded-xl text-sm font-bold transition-all flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-red-600/20 cursor-pointer"
              >
                <Trash2 className="w-4 h-4" />
                {deleting ? "Eliminazione in corso..." : "Elimina Utente"}
              </button>
            </div>
          </div>
        </div>
      )}

      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
