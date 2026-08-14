import { useState } from "react";
import { Eye, EyeOff, LogIn, Shield, User, AlertCircle, Leaf, UserPlus, ArrowLeft, CheckCircle2 } from "lucide-react";
import { loginUser, registerUser } from "@/lib/api";

interface LoginScreenProps {
  onLogin: (user: { name: string; role: string; email: string }) => void;
}

// No more role selection at login -- the account's real role now comes back
// from the server (GET /api/users/login), not a client-side toggle. These
// two entries just drive the "Demo Credentials" hint box, matching the
// accounts seeded by backend/seed_system_users.py.
const DEMO_ACCOUNTS: { email: string; password: string; label: string }[] = [
  { email: "a.reyes@pcic.gov.ph", password: "pcic1234", label: "GIS Specialist" },
  { email: "r.santos@pcic.gov.ph", password: "pcic1234", label: "System Administrator" },
];

type RegRole = "GIS Specialist" | "System Administrator";

interface RegForm {
  fullName: string;
  email: string;
  employeeId: string;
  role: RegRole;
  password: string;
  confirmPassword: string;
  division: string;
}

function RegistrationPanel({ onBack }: { onBack: () => void }) {
  const [form, setForm] = useState<RegForm>({
    fullName: "",
    email: "",
    employeeId: "",
    role: "GIS Specialist",
    password: "",
    confirmPassword: "",
    division: "GIS Risk Assessment Division",
  });
  const [showPw, setShowPw]   = useState(false);
  const [showCPw, setShowCPw] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const update = (key: keyof RegForm, val: string) => {
    setForm(f => ({ ...f, [key]: val }));
    setError(null);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!form.fullName.trim() || !form.email.trim() || !form.employeeId.trim()) {
      setError("Full name, institutional email, and employee ID are required.");
      return;
    }
    if (!form.email.toLowerCase().endsWith("@pcic.gov.ph")) {
      setError("Registration is restricted to @pcic.gov.ph institutional email addresses.");
      return;
    }
    if (form.password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (form.password !== form.confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    registerUser({
      full_name: form.fullName,
      email: form.email,
      employee_id: form.employeeId,
      role: form.role,
      password: form.password,
      division: form.division,
    })
      .then(() => setSuccess(true))
      .catch(error => setError(error instanceof Error ? error.message : "Registration failed."))
      .finally(() => setLoading(false));
  };

  if (success) {
    return (
      <div className="w-full max-w-md">
        <div className="bg-white rounded-2xl shadow-2xl overflow-hidden p-8 flex flex-col items-center text-center">
          <div className="w-14 h-14 rounded-full bg-emerald-100 flex items-center justify-center mb-4">
            <CheckCircle2 size={28} className="text-emerald-600" />
          </div>
          <p className="text-lg font-black text-gray-800">Registration Submitted</p>
          <p className="text-[11px] text-gray-500 mt-2 max-w-xs">
            Your account request has been submitted for administrator approval. You will receive a confirmation email at <strong>{form.email}</strong> once your account is activated.
          </p>
          <p className="text-[10px] text-gray-400 mt-3">Expected activation: 1–2 business days</p>
          <button
            onClick={onBack}
            className="mt-6 flex items-center gap-2 px-5 py-2 rounded-xl bg-[#166534] text-white text-sm font-bold hover:bg-[#14532d] transition-all"
          >
            <ArrowLeft size={14} /> Back to Login
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-md">
      {/* Card */}
      <div className="bg-white rounded-2xl shadow-2xl overflow-hidden">
        <div className="px-6 pt-5 pb-4 border-b border-gray-100 flex items-center gap-2">
          <button
            type="button"
            onClick={onBack}
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-700 transition-colors"
          >
            <ArrowLeft size={14} />
          </button>
          <div>
            <p className="text-sm font-bold text-gray-800">Request System Access</p>
            <p className="text-[10px] text-gray-400">Staff registration — pending administrator approval</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="px-6 pt-4 pb-5 space-y-3">
          {/* Role selector — only GIS Specialist and System Administrator */}
          <div>
            <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Access Role</p>
            <div className="grid grid-cols-2 gap-2">
              {(["GIS Specialist", "System Administrator"] as RegRole[]).map(r => {
                const active = form.role === r;
                return (
                  <button
                    key={r}
                    type="button"
                    onClick={() => update("role", r)}
                    className={`flex items-center gap-2 p-2.5 rounded-xl border-2 transition-all text-left ${
                      active ? "border-[#166534] bg-[#166534]/5" : "border-gray-200 hover:border-gray-300"
                    }`}
                  >
                    <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${active ? "bg-[#166534]" : "bg-gray-100"}`}>
                      {r === "GIS Specialist"
                        ? <User size={12} className={active ? "text-white" : "text-gray-400"} />
                        : <Shield size={12} className={active ? "text-white" : "text-gray-400"} />
                      }
                    </div>
                    <p className={`text-[10px] font-bold leading-tight ${active ? "text-[#166534]" : "text-gray-600"}`}>{r}</p>
                  </button>
                );
              })}
            </div>
            <p className="text-[9px] text-gray-400 mt-1.5">
              Only GIS Specialists and System Administrators may register. Farmer accounts are managed separately through the RSBSA system.
            </p>
          </div>

          {/* Full Name */}
          <div>
            <label className="block text-[11px] font-semibold text-gray-600 mb-1">Full Name</label>
            <input
              type="text"
              value={form.fullName}
              onChange={e => update("fullName", e.target.value)}
              placeholder="e.g. Juan D. Santos"
              className="w-full border border-gray-200 rounded-xl px-3.5 py-2 text-[11px] focus:outline-none focus:border-[#166534] focus:ring-1 focus:ring-[#166534]/30 transition-all placeholder:text-gray-300"
            />
          </div>

          {/* Employee ID + Division */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-[11px] font-semibold text-gray-600 mb-1">Employee ID</label>
              <input
                type="text"
                value={form.employeeId}
                onChange={e => update("employeeId", e.target.value)}
                placeholder="PCIC-XXXX"
                className="w-full border border-gray-200 rounded-xl px-3.5 py-2 text-[11px] focus:outline-none focus:border-[#166534] focus:ring-1 focus:ring-[#166534]/30 transition-all placeholder:text-gray-300"
              />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-gray-600 mb-1">Division</label>
              <select
                value={form.division}
                onChange={e => update("division", e.target.value)}
                className="w-full border border-gray-200 rounded-xl px-3.5 py-2 text-[11px] focus:outline-none focus:border-[#166534] transition-all bg-white"
              >
                <option>GIS Risk Assessment Division</option>
                <option>ICT Division</option>
                <option>Finance Division</option>
                <option>Operations Division</option>
              </select>
            </div>
          </div>

          {/* Email */}
          <div>
            <label className="block text-[11px] font-semibold text-gray-600 mb-1">Institutional Email</label>
            <input
              type="email"
              value={form.email}
              onChange={e => update("email", e.target.value)}
              placeholder="yourname@pcic.gov.ph"
              className="w-full border border-gray-200 rounded-xl px-3.5 py-2 text-[11px] focus:outline-none focus:border-[#166534] focus:ring-1 focus:ring-[#166534]/30 transition-all placeholder:text-gray-300"
            />
          </div>

          {/* Password */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-[11px] font-semibold text-gray-600 mb-1">Password</label>
              <div className="relative">
                <input
                  type={showPw ? "text" : "password"}
                  value={form.password}
                  onChange={e => update("password", e.target.value)}
                  placeholder="Min. 8 characters"
                  className="w-full border border-gray-200 rounded-xl px-3.5 py-2 pr-8 text-[11px] focus:outline-none focus:border-[#166534] focus:ring-1 focus:ring-[#166534]/30 transition-all placeholder:text-gray-300"
                />
                <button type="button" onClick={() => setShowPw(v => !v)} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                  {showPw ? <EyeOff size={12} /> : <Eye size={12} />}
                </button>
              </div>
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-gray-600 mb-1">Confirm Password</label>
              <div className="relative">
                <input
                  type={showCPw ? "text" : "password"}
                  value={form.confirmPassword}
                  onChange={e => update("confirmPassword", e.target.value)}
                  placeholder="Repeat password"
                  className="w-full border border-gray-200 rounded-xl px-3.5 py-2 pr-8 text-[11px] focus:outline-none focus:border-[#166534] focus:ring-1 focus:ring-[#166534]/30 transition-all placeholder:text-gray-300"
                />
                <button type="button" onClick={() => setShowCPw(v => !v)} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                  {showCPw ? <EyeOff size={12} /> : <Eye size={12} />}
                </button>
              </div>
            </div>
          </div>

          {/* Error */}
          {error && (
            <div className="flex items-start gap-2 p-2.5 rounded-xl bg-red-50 border border-red-100">
              <AlertCircle size={12} className="text-red-500 shrink-0 mt-0.5" />
              <p className="text-[10px] text-red-600">{error}</p>
            </div>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl bg-[#166534] hover:bg-[#14532d] text-white text-[11px] font-bold transition-all disabled:opacity-70 shadow-lg shadow-[#166534]/25 mt-1"
          >
            {loading
              ? <><div className="w-3.5 h-3.5 rounded-full border-2 border-white/30 border-t-white animate-spin" />Submitting request…</>
              : <><UserPlus size={13} />Submit Registration Request</>
            }
          </button>
        </form>
      </div>

      <p className="text-center text-white/30 text-[10px] mt-4">
        Authorized Personnel Only · Access requests are reviewed within 1–2 business days
      </p>
    </div>
  );
}

export function LoginScreen({ onLogin }: LoginScreenProps) {
  const [view, setView]         = useState<"login" | "register">("login");
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw]     = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const [loading, setLoading]   = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!email.trim() || !password.trim()) {
      setError("Please enter your email address and password.");
      return;
    }

    setLoading(true);
    loginUser(email.trim(), password)
      .then(result => onLogin(result.user))
      .catch(error => setError(error instanceof Error ? error.message : "Invalid credentials."))
      .finally(() => setLoading(false));
  };

  const fillDemo = (demo: { email: string; password: string }) => {
    setEmail(demo.email);
    setPassword(demo.password);
    setError(null);
  };

  return (
    <div
      className="h-screen overflow-hidden flex flex-col"
      style={{
        background: "linear-gradient(145deg, #0f4023 0%, #166534 40%, #1e3a5f 100%)",
      }}
    >
      {/* Top bar */}
      <div className="flex items-center justify-between px-8 py-[clamp(0.4rem,1.5vh,0.75rem)] shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-white/15 flex items-center justify-center">
            <Leaf size={16} className="text-white" />
          </div>
          <div>
            <p className="text-white text-xs font-bold leading-tight tracking-widest uppercase">Philippine Crop Insurance Corporation</p>
            <p className="text-white/50 text-[9px] leading-tight">Bicol Regional Office — GIS Risk Assessment Division</p>
          </div>
        </div>
        <span className="text-white/30 text-[10px]">v2.1.0-beta</span>
      </div>

      {/* Center -- overflow-y-auto is a safety net for very short viewports;
          the reduced spacing below means it normally fits without scrolling. */}
      <div className="flex-1 min-h-0 overflow-y-auto flex items-center justify-center px-4 py-[clamp(0.25rem,1vh,0.75rem)]">
        {view === "register" ? (
          <RegistrationPanel onBack={() => setView("login")} />
        ) : (
          <div className="w-full max-w-md">
            {/* App Title */}
            <div className="text-center mb-[clamp(0.5rem,1.5vh,1rem)]">
              <h1 className="text-white text-2xl font-black tracking-tight">AgriSureGIS</h1>
              <p className="text-white/60 text-xs mt-1">Automated Disaster Risk Assessment System</p>
              <p className="text-white/40 text-[10px] mt-0.5">Parametric Indemnification · PAGASA TCB Integration · Google Earth Engine</p>
            </div>

            {/* Login Card */}
            <div className="bg-white rounded-2xl shadow-2xl overflow-hidden">
              {/* Card Header */}
              <div className="px-6 pt-[clamp(0.75rem,2vh,1.5rem)] pb-[clamp(0.5rem,1.2vh,1rem)] border-b border-gray-100">
                <p className="text-sm font-bold text-gray-800">Sign in to your account</p>
                <p className="text-[11px] text-gray-400 mt-0.5">Enter your institutional email and password</p>
              </div>

              {/* Form */}
              <form onSubmit={handleSubmit} className="px-6 pt-[clamp(0.75rem,2vh,1.5rem)] pb-[clamp(0.75rem,2vh,1.5rem)]">
                {/* Email */}
                <div className="mb-[clamp(0.4rem,1.2vh,0.75rem)]">
                  <label className="block text-[11px] font-semibold text-gray-600 mb-1.5">Institutional Email</label>
                  <input
                    type="email"
                    value={email}
                    onChange={e => { setEmail(e.target.value); setError(null); }}
                    placeholder="yourname@pcic.gov.ph"
                    className="w-full border border-gray-200 rounded-xl px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#166534] focus:ring-1 focus:ring-[#166534]/30 transition-all placeholder:text-gray-300"
                  />
                </div>

                {/* Password */}
                <div className="mb-[clamp(0.5rem,1.5vh,1rem)]">
                  <label className="block text-[11px] font-semibold text-gray-600 mb-1.5">Password</label>
                  <div className="relative">
                    <input
                      type={showPw ? "text" : "password"}
                      value={password}
                      onChange={e => { setPassword(e.target.value); setError(null); }}
                      placeholder="••••••••"
                      className="w-full border border-gray-200 rounded-xl px-3.5 py-2.5 pr-11 text-sm focus:outline-none focus:border-[#166534] focus:ring-1 focus:ring-[#166534]/30 transition-all placeholder:text-gray-300"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPw(v => !v)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                    >
                      {showPw ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                  </div>
                </div>

                {/* Error */}
                {error && (
                  <div className="flex items-start gap-2 p-3 rounded-xl bg-red-50 border border-red-100 mb-4">
                    <AlertCircle size={13} className="text-red-500 shrink-0 mt-0.5" />
                    <p className="text-[11px] text-red-600">{error}</p>
                  </div>
                )}

                {/* Submit */}
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full flex items-center justify-center gap-2 py-[clamp(0.5rem,1.5vh,0.75rem)] rounded-xl bg-[#166534] hover:bg-[#14532d] text-white text-sm font-bold transition-all disabled:opacity-70 shadow-lg shadow-[#166534]/25"
                >
                  {loading
                    ? <><div className="w-4 h-4 rounded-full border-2 border-white/30 border-t-white animate-spin" />Signing in…</>
                    : <><LogIn size={15} />Sign In to Dashboard</>
                  }
                </button>

                {/* Demo hint */}
                <div className="mt-[clamp(0.4rem,1.2vh,0.75rem)] p-[clamp(0.4rem,1vh,0.625rem)] rounded-xl bg-amber-50 border border-amber-100 space-y-1.5">
                  <p className="text-[10px] font-semibold text-amber-700">Demo Credentials</p>
                  {DEMO_ACCOUNTS.map(demo => (
                    <div key={demo.email} className="flex items-center justify-between gap-2">
                      <div>
                        <p className="text-[10px] text-amber-600 font-mono leading-tight">{demo.email}</p>
                        <p className="text-[9px] text-amber-500 leading-tight">{demo.label} · Password: {demo.password}</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => fillDemo(demo)}
                        className="shrink-0 text-[10px] text-amber-700 underline hover:text-amber-900"
                      >
                        Auto-fill
                      </button>
                    </div>
                  ))}
                </div>

                {/* Register link */}
                <div className="mt-[clamp(0.3rem,1vh,0.5rem)] text-center">
                  <button
                    type="button"
                    onClick={() => setView("register")}
                    className="text-[10px] text-gray-400 hover:text-[#166534] transition-colors inline-flex items-center gap-1"
                  >
                    <UserPlus size={11} /> Request system access (new staff)
                  </button>
                </div>
              </form>
            </div>

            {/* Footer note */}
            <p className="text-center text-white/30 text-[10px] mt-[clamp(0.4rem,1vh,0.75rem)]">
              Authorized Personnel Only · PCIC-GIS AgriSureGIS System · For technical support contact the ICT Division
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
