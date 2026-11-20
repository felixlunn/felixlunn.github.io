import { useState } from "react";

/** Copies this page's address (which records the seat, figure and tab) so staff can send exactly what they see. */
export default function CopyLink({ label = "Copy link" }: { label?: string }) {
  const [done, setDone] = useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(location.href).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); }).catch(() => {});
  };
  return <button className="link small no-print" onClick={copy} title="Copy a link to this seat and figure">{done ? "Link copied" : label}</button>;
}
