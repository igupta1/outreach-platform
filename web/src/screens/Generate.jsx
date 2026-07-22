import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

export default function Generate() {
  const [emails, setEmails] = useState(12);
  const [linkedin, setLinkedin] = useState(0);
  const [pack, setPack] = useState("cfo");
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const poll = useRef();

  useEffect(() => () => clearInterval(poll.current), []);

  async function start() {
    setError(""); setJob(null);
    try {
      const j = await api.generate(Number(emails), Number(linkedin), pack);
      setJob(j);
      clearInterval(poll.current);
      poll.current = setInterval(async () => {
        try {
          const s = await api.generateStatus(j.job_id);
          setJob(s);
          if (s.status !== "running") clearInterval(poll.current);
        } catch (e) {
          setError(e.message); clearInterval(poll.current);
        }
      }, 2000);
    } catch (e) {
      setError(e.message);
    }
  }

  const summary = job?.summary;
  const failures = summary?.results?.filter((r) => r.status === "error" || r.status === "no_gift") || [];

  return (
    <div className="space-y-6">
      <section className="rounded-xl bg-slate-800/60 p-5 ring-1 ring-slate-700">
        <h2 className="text-base font-semibold">Morning quota</h2>
        <p className="mt-1 text-sm text-slate-400">
          Generates that many pending cards — due follow-ups first, then new first-touches.
        </p>
        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <label className="text-sm">Emails
            <input type="number" min="0" value={emails} onChange={(e) => setEmails(e.target.value)}
              className="mt-1 w-full rounded-lg bg-slate-900 px-3 py-2 ring-1 ring-slate-700" />
          </label>
          <label className="text-sm">LinkedIn
            <input type="number" min="0" value={linkedin} onChange={(e) => setLinkedin(e.target.value)}
              className="mt-1 w-full rounded-lg bg-slate-900 px-3 py-2 ring-1 ring-slate-700" />
          </label>
          <label className="text-sm">Pack
            <select value={pack} onChange={(e) => setPack(e.target.value)}
              className="mt-1 w-full rounded-lg bg-slate-900 px-3 py-2 ring-1 ring-slate-700">
              {["cfo", "trucking", "bookkeeping", "pc"].map((p) => <option key={p}>{p}</option>)}
            </select>
          </label>
          <div className="flex items-end">
            <button onClick={start}
              className="w-full rounded-lg bg-accent/90 px-4 py-2 text-sm font-medium text-slate-900 hover:bg-accent">
              Generate
            </button>
          </div>
        </div>
        {error && <p className="mt-3 text-sm text-rose-400">{error}</p>}
      </section>

      {job && (
        <section className="rounded-xl bg-slate-800/60 p-5 ring-1 ring-slate-700">
          <div className="flex items-center gap-2">
            {job.status === "running" && <span className="h-2 w-2 animate-pulse rounded-full bg-amber-400" />}
            <h3 className="text-sm font-semibold">
              Job {job.job_id} — <span className={job.status === "error" ? "text-rose-400" : "text-slate-200"}>{job.status}</span>
            </h3>
          </div>
          {job.error && <p className="mt-2 text-sm text-rose-400">{job.error}</p>}
          {summary && (
            <div className="mt-3 text-sm text-slate-300">
              <p>Generated {summary.generated}/{summary.quota} emails · {summary.first_touches} first-touch · {summary.followups} follow-up</p>
              <p>LinkedIn DMs: {summary.linkedin_generated}/{summary.linkedin_quota}</p>
              {failures.length > 0 && (
                <div className="mt-3 rounded-lg bg-slate-900/70 p-3">
                  <p className="text-rose-300">Surfaced issues ({failures.length}):</p>
                  <ul className="mt-1 space-y-0.5 text-slate-400">
                    {failures.map((f, i) => (
                      <li key={i}>· {f.firm} — {f.status}{f.error ? `: ${f.error}` : ""}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
