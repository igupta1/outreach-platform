import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function LinkedInQueue() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");

  async function load() {
    try { setItems((await api.linkedinQueue()).items); }
    catch (e) { setError(e.message); }
  }
  useEffect(() => { load(); }, []);

  async function toggleConn(id, accepted) {
    try { await api.linkedinConnection(id, accepted); await load(); }
    catch (e) { setError(e.message); }
  }
  async function connectSent(id) {
    try { await api.linkedinConnectSent(id); await load(); }
    catch (e) { setError(e.message); }
  }
  async function dmSent(id) {
    try { await api.linkedinSent(id); await load(); }
    catch (e) { setError(e.message); }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">LinkedIn queue</h2>
        <button onClick={load} className="text-xs text-slate-400 hover:text-slate-200">refresh</button>
      </div>
      <p className="text-sm text-slate-400">
        Day-0 connection requests to send, and approved DMs to paste. Tick “connection accepted” when
        they accept — it gates the next DM.
      </p>
      {error && <p className="text-sm text-rose-400">{error}</p>}

      {items && items.length === 0 && (
        <p className="rounded-xl bg-slate-800/60 p-8 text-center text-slate-500 ring-1 ring-slate-700">
          Nothing queued.
        </p>
      )}
      <div className="space-y-3">
        {items?.map((it) => (
          <div key={`${it.record_id}:${it.kind}`} className="rounded-xl bg-slate-800/60 p-4 ring-1 ring-slate-700">
            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium">
                  {it.firm_name}
                  <span className="ml-2 rounded-full bg-sky-500/15 px-2 py-0.5 text-xs text-sky-300 ring-1 ring-sky-500/30">
                    {it.kind === "connect" ? "connection request" : it.kind.toUpperCase()}
                  </span>
                </p>
                {it.linkedin && <a href={it.linkedin} target="_blank" rel="noreferrer" className="text-xs text-accent">{it.linkedin}</a>}
              </div>
              <label className="flex items-center gap-2 text-xs text-slate-300">
                <input type="checkbox" checked={!!it.connection_accepted}
                  onChange={(e) => toggleConn(it.record_id, e.target.checked)} />
                connection accepted
              </label>
            </div>

            {it.kind === "connect" ? (
              <>
                <p className="mt-2 text-sm text-slate-400 italic">Send a blank connection request (no note).</p>
                <button onClick={() => connectSent(it.record_id)}
                  className="mt-2 rounded-lg bg-slate-700 px-3 py-1 text-xs hover:bg-slate-600">mark connect sent</button>
              </>
            ) : (
              <>
                {it.message?.body && (
                  <pre className="mt-2 whitespace-pre-wrap rounded bg-slate-900/70 p-2 font-sans text-sm text-slate-300">{it.message.body}</pre>
                )}
                <button onClick={() => dmSent(it.record_id)}
                  className="mt-2 rounded-lg bg-slate-700 px-3 py-1 text-xs hover:bg-slate-600">mark DM sent</button>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
