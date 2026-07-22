import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

const NICHES = ["cfo", "trucking", "bookkeeping", "pc"];
const STATUS_COLOR = {
  pending: "text-amber-300",
  in_sequence: "text-sky-300",
  completed: "text-emerald-300",
  do_not_contact: "text-rose-300",
};

export default function Upload() {
  const [niche, setNiche] = useState("cfo");
  const [result, setResult] = useState(null);
  const [queue, setQueue] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef();

  async function loadQueue() {
    try {
      setQueue(await api.prospects());
    } catch (e) {
      setError(e.message);
    }
  }
  useEffect(() => { loadQueue(); }, []);

  async function toggleEligible(rid, val) {
    try { await api.setEligible(rid, val); await loadQueue(); }
    catch (e) { setError(e.message); }
  }

  async function doUpload() {
    const file = fileRef.current?.files?.[0];
    if (!file) return setError("choose a CSV first");
    setBusy(true); setError(""); setResult(null);
    try {
      setResult(await api.uploadCsv(file, niche));
      await loadQueue();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-xl bg-slate-800/60 p-5 ring-1 ring-slate-700">
        <h2 className="text-base font-semibold">Upload prospects (Apollo CSV)</h2>
        <p className="mt-1 text-sm text-slate-400">
          Pick the niche (chooses the NichePack) before uploading. Rows are deduped by domain,
          including against prospects already in the queue.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <select
            value={niche}
            onChange={(e) => setNiche(e.target.value)}
            className="rounded-lg bg-slate-900 px-3 py-2 text-sm ring-1 ring-slate-700"
          >
            {NICHES.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <input ref={fileRef} type="file" accept=".csv" className="text-sm text-slate-300" />
          <button
            onClick={doUpload}
            disabled={busy}
            className="rounded-lg bg-accent/90 px-4 py-2 text-sm font-medium text-slate-900 hover:bg-accent disabled:opacity-50"
          >
            {busy ? "Uploading…" : "Upload"}
          </button>
        </div>
        {error && <p className="mt-3 text-sm text-rose-400">{error}</p>}
        {result && (
          <div className="mt-4 rounded-lg bg-slate-900/70 p-3 text-sm">
            <p className="text-emerald-300">Created {result.created} · skipped {result.skipped}</p>
            {result.skipped_rows?.length > 0 && (
              <ul className="mt-2 space-y-0.5 text-slate-400">
                {result.skipped_rows.slice(0, 20).map((s, i) => (
                  <li key={i}>· {s.firm} — {s.reason}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>

      <section className="rounded-xl bg-slate-800/60 p-5 ring-1 ring-slate-700">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">Pending queue</h2>
          <button onClick={loadQueue} className="text-xs text-slate-400 hover:text-slate-200">refresh</button>
        </div>
        {queue && (
          <div className="mt-2 flex flex-wrap gap-3 text-xs">
            {Object.entries(queue.counts).map(([k, v]) => (
              <span key={k} className={STATUS_COLOR[k] || "text-slate-300"}>{k}: {v}</span>
            ))}
          </div>
        )}
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-slate-500">
              <tr>
                <th className="py-1 pr-3">Firm</th><th className="pr-3">Niche</th>
                <th className="pr-3">Location</th><th className="pr-3">Stage</th>
                <th className="pr-3">Status</th><th>Eligible</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {queue?.prospects?.slice(0, 200).map((p) => (
                <tr key={p.record_id} className="text-slate-300">
                  <td className="py-1.5 pr-3">{p.firm_name}{p.frozen && <span className="ml-1 text-rose-400">❄</span>}</td>
                  <td className="pr-3 text-slate-400">{p.niche_pack}</td>
                  <td className="pr-3 text-slate-400">{[p.city, p.state].filter(Boolean).join(", ")}</td>
                  <td className="pr-3 text-slate-400">{p.stage}</td>
                  <td className={STATUS_COLOR[p.status] || ""}>{p.status}</td>
                  <td>
                    <input type="checkbox" title="eligible_for_send — required to push"
                      checked={!!p.eligible_for_send}
                      onChange={(e) => toggleEligible(p.record_id, e.target.checked)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!queue?.prospects?.length && <p className="mt-3 text-sm text-slate-500">No prospects yet.</p>}
        </div>
      </section>
    </div>
  );
}
