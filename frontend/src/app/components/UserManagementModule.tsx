import { useEffect, useState } from "react";
import { Users, Plus, Save, Settings, Trash2, AlertTriangle } from "lucide-react";
import { getUsers, createUser, updateUser, SystemUser } from "@/lib/api";

// Split out of CalibrationModule.tsx into its own admin tab -- previously a
// collapsed "User Account Management" section nested inside Calibration &
// Settings. Same state/handlers/modals, just no longer nested in an
// accordion.

interface ConfirmDialogProps {
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}

function ConfirmDialog({ message, onConfirm, onCancel }: ConfirmDialogProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-card border border-amber-300 rounded-xl shadow-2xl p-5 max-w-sm">
        <div className="flex items-center gap-2 mb-3">
          <AlertTriangle size={18} className="text-amber-500" />
          <span className="text-sm font-semibold">Confirm Action</span>
        </div>
        <p className="text-xs text-muted-foreground mb-4">{message}</p>
        <div className="flex gap-2">
          <button onClick={onCancel} className="flex-1 py-1.5 rounded-lg border border-border text-xs hover:bg-muted transition-colors">Cancel</button>
          <button onClick={onConfirm} className="flex-1 py-1.5 rounded-lg bg-amber-500 text-white text-xs font-semibold hover:bg-amber-600 transition-colors">Confirm</button>
        </div>
      </div>
    </div>
  );
}

// Only two roles actually mean anything anywhere else in the app (Login's
// role toggle, Registration's own restriction) -- matches
// backend/app/api/users.py's ALLOWED_ROLES, not the prototype's wider
// 4-option dropdown (Data Analyst/Field Supervisor had no backing
// permission logic anywhere).
const USER_ROLES = ["GIS Specialist", "System Administrator"] as const;

export function UserManagementModule() {
  const [users, setUsers] = useState<SystemUser[]>([]);
  const [isLoadingUsers, setIsLoadingUsers] = useState(false);
  const [usersError, setUsersError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<{ msg: string; fn: () => void } | null>(null);

  const [editingUser, setEditingUser] = useState<SystemUser | null>(null);
  const [addingUser, setAddingUser]   = useState(false);
  const [newUser, setNewUser]         = useState({ name:"", role:"GIS Specialist", email:"", password:"" });
  const [userActionError, setUserActionError] = useState<string | null>(null);

  const loadUsers = () => {
    setIsLoadingUsers(true);
    setUsersError(null);
    getUsers()
      .then(res => setUsers(res.data))
      .catch(error => setUsersError(error instanceof Error ? error.message : "Failed to load users."))
      .finally(() => setIsLoadingUsers(false));
  };

  useEffect(() => { loadUsers(); }, []);

  const handleDeleteUser = (id: number) => {
    setConfirm({
      msg: "Are you sure you want to deactivate this user account? This action can be reversed by an administrator.",
      fn: () => {
        setUserActionError(null);
        updateUser(id, { is_active: false })
          .then(res => setUsers(u => u.map(x => x.user_id === id ? res.data : x)))
          .catch(error => setUserActionError(error instanceof Error ? error.message : "Failed to deactivate user."))
          .finally(() => setConfirm(null));
      },
    });
  };

  const handleSaveEditUser = () => {
    if (!editingUser) return;
    setUserActionError(null);
    updateUser(editingUser.user_id, {
      name: editingUser.name,
      email: editingUser.email,
      role: editingUser.role,
      is_active: editingUser.is_active,
      session_timeout_minutes: editingUser.session_timeout_minutes,
    })
      .then(res => {
        setUsers(u => u.map(x => x.user_id === editingUser.user_id ? res.data : x));
        setEditingUser(null);
      })
      .catch(error => setUserActionError(error instanceof Error ? error.message : "Failed to save changes."));
  };

  const handleAddUser = () => {
    if (!newUser.name.trim() || !newUser.email.trim()) return;
    setUserActionError(null);
    createUser(newUser)
      .then(res => {
        setUsers(u => [...u, res.data]);
        setNewUser({ name:"", role:"GIS Specialist", email:"", password:"" });
        setAddingUser(false);
      })
      .catch(error => setUserActionError(error instanceof Error ? error.message : "Failed to create user."));
  };

  return (
    <div className="h-full overflow-auto bg-background p-4">
      {confirm && <ConfirmDialog message={confirm.msg} onConfirm={confirm.fn} onCancel={() => setConfirm(null)} />}

      {/* Edit User Modal */}
      {editingUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-card border border-border rounded-2xl shadow-2xl w-[420px] overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <div className="flex items-center gap-2">
                <Users size={15} className="text-[#166534]" />
                <p className="text-sm font-bold">Edit User Account</p>
              </div>
              <button onClick={() => setEditingUser(null)} className="text-muted-foreground hover:text-foreground">✕</button>
            </div>
            <div className="p-4">
              <div className="p-3 rounded-xl bg-muted/40 border border-border space-y-3">
                {[
                  { label:"Full Name", key:"name" as const, type:"text" },
                  { label:"Email",     key:"email" as const, type:"email" },
                ].map(f => (
                  <div key={f.key}>
                    <label className="text-[11px] font-semibold block mb-1">{f.label}</label>
                    <input
                      type={f.type}
                      value={editingUser[f.key]}
                      onChange={e => setEditingUser({ ...editingUser, [f.key]: e.target.value })}
                      className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
                    />
                  </div>
                ))}
                <div>
                  <label className="text-[11px] font-semibold block mb-1">Role</label>
                  <select
                    value={editingUser.role}
                    onChange={e => setEditingUser({ ...editingUser, role: e.target.value })}
                    className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
                  >
                    {USER_ROLES.map(r => <option key={r}>{r}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-[11px] font-semibold block mb-1">Session Timeout</label>
                  <select
                    value={editingUser.session_timeout_minutes}
                    onChange={e => setEditingUser({ ...editingUser, session_timeout_minutes: Number(e.target.value) })}
                    className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
                  >
                    {[0, 5, 10, 15, 30].map(v => <option key={v} value={v}>{v === 0 ? "Disabled" : `${v} minutes`}</option>)}
                  </select>
                  <p className="mt-1 text-[9px] text-muted-foreground">Auto-logout after this many idle minutes -- follows this account to any device.</p>
                </div>
                <div className="flex items-center gap-2 pt-1">
                  <input type="checkbox" id="activeToggle" checked={editingUser.is_active} onChange={e => setEditingUser({ ...editingUser, is_active: e.target.checked })} className="accent-[#166534]" />
                  <label htmlFor="activeToggle" className="text-[11px]">Account Active</label>
                </div>
              </div>
              {userActionError && <p className="text-[10px] text-red-600 mt-2">{userActionError}</p>}
            </div>
            <div className="flex gap-2 px-4 py-3 border-t border-border justify-end">
              <button onClick={() => setEditingUser(null)} className="px-3 py-1.5 rounded-lg border border-border text-xs hover:bg-muted transition-colors">Cancel</button>
              <button onClick={handleSaveEditUser} className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-[#166534] text-white text-xs font-semibold hover:bg-[#14532d] transition-colors">
                <Save size={11} /> Save Changes
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add User Modal */}
      {addingUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-card border border-border rounded-2xl shadow-2xl w-[420px] overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <div className="flex items-center gap-2">
                <Users size={15} className="text-[#166534]" />
                <p className="text-sm font-bold">Add New User Account</p>
              </div>
              <button onClick={() => setAddingUser(false)} className="text-muted-foreground hover:text-foreground">✕</button>
            </div>
            <div className="p-4">
              <div className="p-3 rounded-xl bg-muted/40 border border-border space-y-3">
                {[
                  { label:"Full Name",        key:"name" as const,     type:"text"     },
                  { label:"Email Address",    key:"email" as const,    type:"email"    },
                  { label:"Temp. Password",   key:"password" as const, type:"password" },
                ].map(f => (
                  <div key={f.key}>
                    <label className="text-[11px] font-semibold block mb-1">{f.label}</label>
                    <input
                      type={f.type}
                      value={newUser[f.key]}
                      onChange={e => setNewUser({ ...newUser, [f.key]: e.target.value })}
                      placeholder={f.label}
                      className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
                    />
                  </div>
                ))}
                <div>
                  <label className="text-[11px] font-semibold block mb-1">Role</label>
                  <select
                    value={newUser.role}
                    onChange={e => setNewUser({ ...newUser, role: e.target.value })}
                    className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
                  >
                    {USER_ROLES.map(r => <option key={r}>{r}</option>)}
                  </select>
                </div>
              </div>
              {(!newUser.name.trim() || !newUser.email.trim()) && (
                <p className="text-[10px] text-amber-600 mt-2">Name and email are required.</p>
              )}
              {userActionError && <p className="text-[10px] text-red-600 mt-2">{userActionError}</p>}
            </div>
            <div className="flex gap-2 px-4 py-3 border-t border-border justify-end">
              <button onClick={() => setAddingUser(false)} className="px-3 py-1.5 rounded-lg border border-border text-xs hover:bg-muted transition-colors">Cancel</button>
              <button
                onClick={handleAddUser}
                disabled={!newUser.name.trim() || !newUser.email.trim()}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-[#166534] text-white text-xs font-semibold hover:bg-[#14532d] disabled:opacity-50 transition-colors"
              >
                <Plus size={11} /> Create Account
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="max-w-5xl mx-auto space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-bold text-foreground flex items-center gap-2">
              <Users size={18} className="text-[#166534]" /> User Management
            </h2>
            <p className="text-[11px] text-muted-foreground mt-0.5">Manage system access for GIS specialists and administrators.</p>
          </div>
          <button
            onClick={() => setAddingUser(true)}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#166534] text-white text-xs font-semibold hover:bg-[#14532d] transition-colors"
          >
            <Plus size={13} /> Add User
          </button>
        </div>

        <div className="bg-card border border-border rounded-xl overflow-hidden px-4 py-4">
          {usersError && (
            <p className="text-[10px] text-red-600 mb-2">{usersError}</p>
          )}
          {isLoadingUsers && users.length === 0 ? (
            <p className="text-[11px] text-muted-foreground py-4 text-center">Loading users…</p>
          ) : users.length === 0 ? (
            <p className="text-[11px] text-muted-foreground py-4 text-center">No user accounts yet.</p>
          ) : (
            <table className="w-full text-[11px]">
              <thead>
                <tr className="bg-muted/60 text-muted-foreground">
                  <th className="px-3 py-2 text-left font-semibold">Name</th>
                  <th className="px-3 py-2 text-left font-semibold">Role</th>
                  <th className="px-3 py-2 text-left font-semibold">Email</th>
                  <th className="px-3 py-2 text-left font-semibold">Status</th>
                  <th className="px-3 py-2 text-left font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map(u => (
                  <tr key={u.user_id} className="border-t border-border">
                    <td className="px-3 py-2.5 font-medium">{u.name}</td>
                    <td className="px-3 py-2.5 text-muted-foreground">{u.role}</td>
                    <td className="px-3 py-2.5 text-muted-foreground font-mono text-[10px]">{u.email}</td>
                    <td className="px-3 py-2.5">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${u.is_active?"bg-emerald-100 text-emerald-700":"bg-gray-100 text-gray-500"}`}>
                        {u.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => setEditingUser(u)}
                          className="p-1 hover:bg-muted rounded text-[#1e3a5f]"
                          title="Edit"
                        >
                          <Settings size={11} />
                        </button>
                        {u.is_active && (
                          <button
                            className="p-1 hover:bg-muted rounded text-destructive"
                            title="Deactivate"
                            onClick={() => handleDeleteUser(u.user_id)}
                          >
                            <Trash2 size={11} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="pb-6" />
      </div>
    </div>
  );
}
