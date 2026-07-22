import React, { useState } from "react";
import { getToken, setToken, clearToken } from "./api.js";
import Upload from "./screens/Upload.jsx";
import Generate from "./screens/Generate.jsx";
import Flashcards from "./screens/Flashcards.jsx";
import LinkedInQueue from "./screens/LinkedInQueue.jsx";

const TABS = [
  { key: "upload", label: "Upload", el: Upload },
  { key: "generate", label: "Generate", el: Generate },
  { key: "review", label: "Review", el: Flashcards },
  { key: "linkedin", label: "LinkedIn", el: LinkedInQueue },
];

function TokenGate({ onSet }) {
  const [t, setT] = useState("");
  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="w-full max-w-sm rounded-xl bg-slate-800/70 p-6 ring-1 ring-slate-700">
        <h1 className="text-lg font-semibold">System B — Operator</h1>
        <p className="mt-1 text-sm text-slate-400">Enter the access token to continue.</p>
        <input
          type="password"
          value={t}
          onChange={(e) => setT(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && t && onSet(t)}
          placeholder="UI_AUTH_TOKEN"
          className="mt-4 w-full rounded-lg bg-slate-900 px-3 py-2 text-sm ring-1 ring-slate-700 focus:outline-none focus:ring-accent"
        />
        <button
          onClick={() => t && onSet(t)}
          className="mt-3 w-full rounded-lg bg-accent/90 px-3 py-2 text-sm font-medium text-slate-900 hover:bg-accent"
        >
          Continue
        </button>
      </div>
    </div>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  const [tab, setTab] = useState("review");
  if (!authed) return <TokenGate onSet={(t) => { setToken(t); setAuthed(true); }} />;

  const Active = TABS.find((t) => t.key === tab).el;
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-slate-800 bg-slate-900/80 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-1">
            <span className="mr-3 text-sm font-semibold text-slate-300">System B</span>
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`rounded-lg px-3 py-1.5 text-sm ${
                  tab === t.key ? "bg-accent/20 text-accent" : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => { clearToken(); setAuthed(false); }}
            className="text-xs text-slate-500 hover:text-slate-300"
          >
            sign out
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6">
        <Active />
      </main>
    </div>
  );
}
