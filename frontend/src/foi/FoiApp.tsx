import { useEffect, useState } from "react";
import type { Backend, User } from "./backend";
import { type Reference } from "./types";
import { Login, SetPassword } from "./Auth";
import { Workspace } from "./Workspace";


export default function FoiApp({ backend, ref_, shapes }: { backend: Backend; ref_: Reference; shapes: GeoJSON.FeatureCollection }) {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [recovery, setRecovery] = useState(false);
  const [membership, setMembership] = useState<{ member: boolean; admin: boolean; error?: string } | null>(null);

  useEffect(() => {
    backend.user().then(setUser);
    return backend.onChange((u, ev) => { setUser(u); if (ev === "recovery") setRecovery(true); });
  }, [backend]);
  useEffect(() => {
    setMembership(null);
    if (user) backend.membership().then(setMembership).catch((e: Error) => setMembership({ member: false, admin: false, error: e.message }));
  }, [backend, user]);

  if (user === undefined) return <div className="boot">Checking your login…</div>;
  if (recovery && user) return <SetPassword backend={backend} onDone={() => setRecovery(false)} />;
  if (!user) return <Login backend={backend} />;
  if (!membership) return <div className="boot">Checking your access…</div>;
  if (!membership.member) {
    return (
      <div className="foi-gate">
        <div className="foi-gate-box">
          <h1>No access yet</h1>
          {membership.error ? (
            <p className="small">You're signed in as <strong>{user.email}</strong>, but the team list couldn't be checked: <span className="bad">{membership.error}</span>.
              If it mentions permission, re-run <code>supabase/schema.sql</code> in the Supabase SQL Editor.</p>
          ) : (
            <p className="small">You're signed in as <strong>{user.email}</strong>, but this address isn't on the FOI research team list. Ask the person who invited you to add it.</p>
          )}
          <button className="btn" onClick={() => backend.signOut()}>Sign out</button>
        </div>
      </div>
    );
  }
  return <Workspace backend={backend} user={user} admin={membership.admin} ref_={ref_} shapes={shapes} />;
}
