/**
 * Where FOI datasets live. Production: Supabase (Postgres with row-level security, email + password logins,
 * a private file bucket); see supabase/schema.sql. Local development without Supabase settings: a demo backend
 * that keeps everything in this browser only.
 */

import { normaliseDataset, normaliseDatasets } from "./contract";
import type { Dataset, DatasetInfo, DatasetSummary, Department, NewDataset } from "./types";

export interface User { id: string; email: string }

export interface Backend {
  kind: "supabase" | "demo";
  /** The signed-in user, or null. */
  user(): Promise<User | null>;
  /** Called on sign in / out, and with "recovery" when a password reset or invite link was opened. */
  onChange(cb: (u: User | null, event?: "recovery") => void): () => void;
  signIn(email: string, password: string): Promise<void>;
  signOut(): Promise<void>;
  sendReset(email: string): Promise<void>;
  setPassword(password: string): Promise<void>;
  /** Whether the user is on the team list (foi_members), and their role. */
  membership(): Promise<{ member: boolean; admin: boolean }>;
  /** A department's datasets without their rows (small and quick, however much has been uploaded), newest first. */
  list(dept: Department): Promise<DatasetInfo[]>;
  /** One dataset with its rows. */
  get(id: string): Promise<Dataset>;
  /** Every dataset in a department with its rows: for Area view, which compares them all. */
  all(dept: Department): Promise<Dataset[]>;
  create(d: NewDataset, file: File | null): Promise<Dataset>;
  update(id: string, patch: Partial<NewDataset>): Promise<Dataset>;
  remove(d: Dataset): Promise<void>;
  /** A short-lived link to the original uploaded file. */
  fileUrl(path: string): Promise<string>;
}

/** The project address only: a URL copied with a path such as /rest/v1/ makes every login fail ("Invalid path"). */
export function projectUrl(raw: string | undefined): string | undefined {
  if (!raw?.trim()) return undefined;
  try { return new URL(raw.trim()).origin; } catch { return raw.trim(); }
}

const URL_ = projectUrl(import.meta.env.VITE_SUPABASE_URL as string | undefined);
const KEY = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

export const configured = Boolean(URL_ && KEY);
/** Demo storage is only offered in development (or when explicitly enabled), never silently in production. */
export const demoAllowed = import.meta.env.DEV || import.meta.env.VITE_FOI_DEMO === "1";

export async function getBackend(): Promise<Backend | null> {
  if (configured) return supabaseBackend(URL_!, KEY!);
  if (demoAllowed) return demoBackend();
  return null;
}

/**
 * Add ready-made public datasets (e.g. police.uk by force, from foi/police.json) to a backend: they're listed and
 * opened like uploads, in their department, but can't be changed or deleted.
 */
export function withBuiltins(b: Backend, builtins: Dataset[]): Backend {
  if (!builtins.length) return b;
  const forDept = (dept: Department) => builtins.filter((d) => d.department === dept);
  const isBuiltin = (id: string) => builtins.some((d) => d.id === id);
  return {
    ...b,
    async list(dept) { return [...(await b.list(dept)), ...forDept(dept).map(withoutRows)]; },
    async get(id) { return builtins.find((d) => d.id === id) ?? b.get(id); },
    async all(dept) { return [...(await b.all(dept)), ...forDept(dept)]; },
    async update(id, patch) { if (isBuiltin(id)) throw new Error("Ready-made datasets can't be changed."); return b.update(id, patch); },
    async remove(d) { if (isBuiltin(d.id)) throw new Error("Ready-made datasets can't be deleted."); return b.remove(d); },
  };
}

/** Everything but the rows, for listing. */
export function withoutRows(d: Dataset): DatasetInfo {
  const { rows: _rows, unmatched: _unmatched, ...info } = d;
  return { ...info, summary: d.summary ?? countOnly(d) };
}

/** A summary for datasets saved before summaries were: the sizes, without a headline. */
function countOnly(d: Dataset): DatasetSummary {
  return { rows: d.rows.length, unmatched: d.unmatched.length, headline: null };
}

const INFO_FIELDS = "id,department,geography,title,foi_reference,authority,period,requested_on,received_on,notes,columns,summary,file_path,created_by,created_by_email,created_at,updated_at";

/** The database hasn't had the "summary" column added yet (supabase/schema.sql): fall back to the old way. */
export function noSummaryColumn(e: { code?: string; message: string } | null): boolean {
  return !!e && /summary/.test(e.message) && (e.code === "42703" || e.code === "PGRST204" || /column/i.test(e.message));
}

function safeName(name: string): string {
  return name.replace(/[^A-Za-z0-9._-]+/g, "_").slice(-100);
}

async function supabaseBackend(url: string, key: string): Promise<Backend> {
  // Invite and reset links arrive as #...type=invite|recovery: read it before the client consumes the link.
  const linkType = new URLSearchParams(location.hash.slice(1)).get("type");
  let pendingRecovery = linkType === "invite" || linkType === "recovery";
  const { createClient } = await import("@supabase/supabase-js");
  const sb = createClient(url, key, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true, flowType: "implicit" } });
  const toUser = (u: { id: string; email?: string } | null | undefined): User | null => (u ? { id: u.id, email: u.email ?? "" } : null);
  const fail = (e: { message: string } | null) => { if (e) throw new Error(e.message); };
  // Set once the database turns out not to have the summary column yet.
  let legacy = false;
  const all = async (dept: Department): Promise<Dataset[]> => {
    const { data, error } = await sb.from("foi_datasets").select("*").eq("department", dept).order("created_at", { ascending: false });
    fail(error);
    return normaliseDatasets(data ?? []);
  };

  return {
    kind: "supabase",
    async user() { return toUser((await sb.auth.getSession()).data.session?.user); },
    onChange(cb) {
      const { data } = sb.auth.onAuthStateChange((event, session) => {
        if (event === "PASSWORD_RECOVERY") pendingRecovery = true;
        cb(toUser(session?.user), pendingRecovery ? "recovery" : undefined);
      });
      return () => data.subscription.unsubscribe();
    },
    async signIn(email, password) { fail((await sb.auth.signInWithPassword({ email: email.trim(), password })).error); },
    async signOut() { await sb.auth.signOut(); },
    async sendReset(email) {
      fail((await sb.auth.resetPasswordForEmail(email.trim(), { redirectTo: location.origin + location.pathname })).error);
    },
    async setPassword(password) {
      fail((await sb.auth.updateUser({ password })).error);
      pendingRecovery = false;
      history.replaceState(null, "", location.pathname);
    },
    async membership() {
      const u = (await sb.auth.getUser()).data.user;
      if (!u?.email) return { member: false, admin: false };
      const { data, error } = await sb.from("foi_members").select("role").eq("email", u.email.toLowerCase()).maybeSingle();
      if (error) throw new Error(error.message);
      return { member: !!data, admin: data?.role === "admin" };
    },
    async list(dept) {
      if (!legacy) {
        const { data, error } = await sb.from("foi_datasets").select(INFO_FIELDS).eq("department", dept).order("created_at", { ascending: false });
        if (!noSummaryColumn(error)) {
          fail(error);
          return normaliseDatasets(data ?? []).map(withoutRows);
        }
        legacy = true;
        console.warn("FOI: the database has no summary column yet; run the latest supabase/schema.sql. Loading full datasets meanwhile.");
      }
      return (await all(dept)).map(withoutRows);
    },
    async get(id) {
      const { data, error } = await sb.from("foi_datasets").select("*").eq("id", id).single();
      fail(error);
      const d = normaliseDataset(data);
      if (!d) throw new Error("This dataset couldn't be read.");
      return d;
    },
    all,
    async create(d, file) {
      const u = (await sb.auth.getUser()).data.user;
      let file_path: string | null = null;
      if (file && u) {
        file_path = `${u.id}/${Date.now()}-${safeName(file.name)}`;
        fail((await sb.storage.from("foi-files").upload(file_path, file, { upsert: false })).error);
      }
      const insert = (row: object) => sb.from("foi_datasets").insert({ ...row, file_path }).select().single();
      let { data, error } = await insert(legacy ? { ...d, summary: undefined } : d);
      if (!legacy && noSummaryColumn(error)) {
        legacy = true;
        ({ data, error } = await insert({ ...d, summary: undefined }));
      }
      if (error && file_path) await sb.storage.from("foi-files").remove([file_path]);
      fail(error);
      return normaliseDataset(data)!;
    },
    async update(id, patch) {
      const { data, error } = await sb.from("foi_datasets").update(patch).eq("id", id).select().single();
      fail(error);
      return normaliseDataset(data)!;
    },
    async remove(d) {
      fail((await sb.from("foi_datasets").delete().eq("id", d.id)).error);
      if (d.file_path) await sb.storage.from("foi-files").remove([d.file_path]);
    },
    async fileUrl(path) {
      const { data, error } = await sb.storage.from("foi-files").createSignedUrl(path, 300);
      fail(error);
      return data!.signedUrl;
    },
  };
}

/** Development only: datasets kept in this browser's localStorage; any email and password signs in. */
function demoBackend(): Backend {
  const KEY_DATA = "foi.demo.datasets", KEY_USER = "foi.demo.user";
  const read = (): Dataset[] => { try { return JSON.parse(localStorage.getItem(KEY_DATA) || "[]"); } catch { return []; } };
  const write = (ds: Dataset[]) => { try { localStorage.setItem(KEY_DATA, JSON.stringify(ds)); } catch { /* storage full or blocked */ } };
  const listeners = new Set<(u: User | null) => void>();
  const current = (): User | null => { try { const e = localStorage.getItem(KEY_USER); return e ? { id: e, email: e } : null; } catch { return null; } };
  const emit = () => listeners.forEach((cb) => cb(current()));
  const all = (dept: Department) => normaliseDatasets(read()).filter((d) => d.department === dept).sort((a, b) => b.created_at.localeCompare(a.created_at));
  return {
    kind: "demo",
    async user() { return current(); },
    onChange(cb) { listeners.add(cb); return () => listeners.delete(cb); },
    async signIn(email, password) {
      if (!email.includes("@") || !password) throw new Error("Enter an email address and any password (demo mode).");
      try { localStorage.setItem(KEY_USER, email.trim().toLowerCase()); } catch { /* ignore */ }
      emit();
    },
    async signOut() { try { localStorage.removeItem(KEY_USER); } catch { /* ignore */ } emit(); },
    async sendReset() { /* nothing to send in demo mode */ },
    async setPassword() { /* nothing to set in demo mode */ },
    async membership() { return { member: true, admin: true }; },
    async list(dept) { return all(dept).map(withoutRows); },
    async get(id) {
      const d = normaliseDatasets(read()).find((x) => x.id === id);
      if (!d) throw new Error("This dataset has been deleted.");
      return d;
    },
    async all(dept) { return all(dept); },
    async create(d) {
      const u = current();
      const now = new Date().toISOString();
      const ds: Dataset = { ...d, file_path: null, id: crypto.randomUUID(), created_by: u?.id ?? null, created_by_email: u?.email ?? "", created_at: now, updated_at: now };
      write([ds, ...read()]);
      return ds;
    },
    async update(id, patch) {
      const all = read();
      const i = all.findIndex((d) => d.id === id);
      all[i] = { ...all[i], ...patch, updated_at: new Date().toISOString() };
      write(all);
      return all[i];
    },
    async remove(d) { write(read().filter((x) => x.id !== d.id)); },
    async fileUrl() { throw new Error("Original files aren't kept in demo mode."); },
  };
}
