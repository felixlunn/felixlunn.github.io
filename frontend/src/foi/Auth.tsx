import { useState } from "react";
import type { Backend } from "./backend";


/** Signing in, and choosing a password from an invite or reset link. */

export function Login({ backend }: { backend: Backend }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try { await backend.signIn(email, password); } catch (err) { setMsg({ text: (err as Error).message, bad: true }); } finally { setBusy(false); }
  };
  const reset = async () => {
    if (!email.includes("@")) { setMsg({ text: "Enter your email address first, then choose “Forgotten password”.", bad: true }); return; }
    try { await backend.sendReset(email); setMsg({ text: "If that address is on the team, a link to set a new password is on its way." }); }
    catch (err) { setMsg({ text: (err as Error).message, bad: true }); }
  };
  return (
    <div className="foi-gate">
      <form className="foi-gate-box" onSubmit={submit}>
        <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true"><rect width="32" height="32" rx="6" fill="var(--accent)" /><path d="M9 8h14M9 14h10M9 20h12M9 26h7" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" /></svg>
        <h1>FOI research</h1>
        <p className="small muted">For the research team only. Accounts are by invitation.</p>
        {backend.kind === "demo" && <p className="tiny warn">Demo mode: no database is set up, so anything uploaded stays in this browser. Any email and password will do.</p>}
        <label className="foi-field"><span>Email</span><input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <label className="foi-field"><span>Password</span><input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        {msg && <p className={`small ${msg.bad ? "bad" : ""}`} role="status">{msg.text}</p>}
        <button className="btn primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <button type="button" className="link-btn tiny" onClick={reset}>Forgotten password</button>
        <a className="tiny" href="./">Back to the dashboard</a>
      </form>
    </div>
  );
}

export function SetPassword({ backend, onDone }: { backend: Backend; onDone: () => void }) {
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pw.length < 10) return setErr("Use at least 10 characters.");
    if (pw !== pw2) return setErr("The two passwords don't match.");
    try { await backend.setPassword(pw); onDone(); } catch (x) { setErr((x as Error).message); }
  };
  return (
    <div className="foi-gate">
      <form className="foi-gate-box" onSubmit={submit}>
        <h1>Choose a password</h1>
        <label className="foi-field"><span>New password</span><input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} /></label>
        <label className="foi-field"><span>Again</span><input type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} /></label>
        {err && <p className="small bad">{err}</p>}
        <button className="btn primary">Save password</button>
      </form>
    </div>
  );
}
