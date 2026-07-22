import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

const BADGE = {
  slate: "bg-slate-500/15 text-slate-300 ring-slate-500/30",
  sky: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
};
function Badge({ children, color = "slate" }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs ring-1 ${BADGE[color] || BADGE.slate}`}>
      {children}
    </span>
  );
}

function Lead({ lead }) {
  const dot = lead.date_confidence === "high" ? "bg-emerald-400" : "bg-amber-400";
  return (
    <div className="rounded-lg bg-slate-900/60 p-3 ring-1 ring-slate-800">
      <div className="flex items-center gap-2">
        <span className="font-medium text-slate-100">{lead.company}</span>
        {lead.best && <span className="text-xs text-amber-300">★ BEST</span>}
        <span className="text-xs text-slate-400">[{lead.signal_type}]</span>
        <span className="text-xs text-slate-500">match L{lead.match_level}</span>
      </div>
      {lead.value_prop && <p className="mt-1 text-sm text-slate-400">{lead.value_prop}</p>}
      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
        {lead.domainless ? (
          <span className="text-rose-300">DOMAINLESS</span>
        ) : (
          <span className="text-slate-400">{lead.domain}</span>
        )}
        <span className="inline-flex items-center gap-1 text-slate-400">
          <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
          {lead.date || "?"} ({lead.date_confidence})
        </span>
        <span className="text-slate-500">{lead.freshness}</span>
      </div>
    </div>
  );
}

export default function Flashcards() {
  const [channel, setChannel] = useState("");
  const [cards, setCards] = useState([]);
  const [total, setTotal] = useState(0);
  const [i, setI] = useState(0);
  const [editing, setEditing] = useState(false);
  const [subj, setSubj] = useState("");
  const [body, setBody] = useState("");
  const [note, setNote] = useState(null); // {type, text, warnings?}
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const card = cards[i];

  const load = useCallback(async () => {
    setLoading(true); setNote(null);
    try {
      const res = await api.cards(channel || undefined);
      setCards(res.cards);
      setTotal(res.total);
      setI(0);
    } catch (e) {
      setNote({ type: "error", text: e.message });
    } finally {
      setLoading(false);
    }
  }, [channel]);

  useEffect(() => { load(); }, [load]);

  function resetEdit(c) {
    setEditing(false);
    setSubj(c?.message?.subject || "");
    setBody(c?.message?.body || "");
  }
  useEffect(() => { resetEdit(card); setNote(null); }, [i, cards]); // eslint-disable-line

  function drop() {
    // remove the current card and stay at the same index (next card slides in)
    setCards((cs) => cs.filter((_, idx) => idx !== i));
    setI((idx) => Math.min(idx, cards.length - 2 < 0 ? 0 : cards.length - 2));
  }
  const next = () => setI((idx) => Math.min(idx + 1, cards.length - 1));

  const doApprove = useCallback(async () => {
    if (!card || busy) return;
    setBusy(true); setNote(null);
    try {
      const r = await api.approve(card.record_id, null, card.channel);
      if (r.approved && (r.pushed || r.channel === "linkedin")) {
        drop();
      } else {
        setNote({ type: "error", text: `Not sent — ${r.error || "push failed"}. Card kept for retry.` });
      }
    } catch (e) {
      setNote({ type: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  }, [card, busy, i, cards]); // eslint-disable-line

  const doReject = useCallback(async () => {
    if (!card || busy) return;
    setBusy(true);
    try { await api.reject(card.record_id, card.channel); drop(); }
    catch (e) { setNote({ type: "error", text: e.message }); }
    finally { setBusy(false); }
  }, [card, busy, i, cards]); // eslint-disable-line

  const doSaveEdit = useCallback(async () => {
    if (!card) return;
    setBusy(true);
    try {
      const r = await api.edit(card.record_id, subj, body, card.channel);
      // reflect the cleaned body + surface honesty warnings
      setCards((cs) => cs.map((c, idx) => idx === i ? { ...c, message: { subject: subj, body: r.cleaned_body } } : c));
      setBody(r.cleaned_body);
      setEditing(false);
      setNote({ type: r.warnings.length ? "warn" : "ok",
                text: r.warnings.length ? "" : "Edit saved.", warnings: r.warnings });
    } catch (e) {
      setNote({ type: "error", text: e.message });
    } finally { setBusy(false); }
  }, [card, subj, body, i]);

  const doSkip = useCallback(() => { if (card) { api.skip(card.record_id).catch(() => {}); next(); } }, [card, cards]); // eslint-disable-line

  const toggleEligible = useCallback(async () => {
    if (!card) return;
    try {
      const val = !card.eligible_for_send;
      await api.setEligible(card.record_id, val);
      setCards((cs) => cs.map((c, idx) => idx === i ? { ...c, eligible_for_send: val } : c));
    } catch (e) { setNote({ type: "error", text: e.message }); }
  }, [card, i]);

  // keyboard shortcuts (ignored while typing in the edit fields)
  useEffect(() => {
    function onKey(e) {
      const typing = ["INPUT", "TEXTAREA"].includes(e.target.tagName);
      if (editing) {
        if (e.key === "Escape") resetEdit(card);
        if ((e.metaKey || e.ctrlKey) && e.key === "Enter") doSaveEdit();
        return;
      }
      if (typing) return;
      if (e.key === "a") doApprove();
      else if (e.key === "r") doReject();
      else if (e.key === "e") { setEditing(true); }
      else if (e.key === "s") doSkip();
      else if (e.key === "ArrowRight" || e.key === " ") { e.preventDefault(); next(); }
      else if (e.key === "ArrowLeft") setI((idx) => Math.max(0, idx - 1));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editing, card, doApprove, doReject, doSkip, doSaveEdit]); // eslint-disable-line

  if (loading) return <p className="text-slate-400">Loading cards…</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex gap-1">
          {["", "email", "linkedin"].map((c) => (
            <button key={c || "all"} onClick={() => setChannel(c)}
              className={`rounded-lg px-3 py-1 text-sm ${channel === c ? "bg-accent/20 text-accent" : "text-slate-400 hover:text-slate-200"}`}>
              {c || "all"}
            </button>
          ))}
        </div>
        <div className="text-sm text-slate-400">
          {cards.length ? `card ${i + 1} of ${cards.length}` : "0 cards"} · {total} pending total
          <button onClick={load} className="ml-3 text-xs text-slate-500 hover:text-slate-300">refresh</button>
        </div>
      </div>

      {!card ? (
        <p className="rounded-xl bg-slate-800/60 p-8 text-center text-slate-400 ring-1 ring-slate-700">
          No cards to review. Generate some on the Generate tab.
        </p>
      ) : (
        <div className="rounded-xl bg-slate-800/60 p-5 ring-1 ring-slate-700">
          {/* header */}
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">{card.prospect.firm_name}</h2>
              <p className="text-sm text-slate-400">
                {[card.prospect.city, card.prospect.state].filter(Boolean).join(", ")}
                {card.prospect.first_name ? ` · ${card.prospect.first_name}` : ""}
              </p>
              <p className="text-xs text-slate-500">
                {card.prospect.email}{card.prospect.linkedin ? ` · ${card.prospect.linkedin}` : ""}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge color="sky">{card.channel}</Badge>
              <Badge color="slate">{card.step_label}</Badge>
              {card.left_field_variant && <Badge color="slate">variant {card.left_field_variant}</Badge>}
            </div>
          </div>

          {/* classification + evidence */}
          <div className="mt-3 text-sm">
            {card.prospect.classification === "niched" ? (
              <p className="text-slate-300">
                niched: <span className="text-accent">{card.prospect.match_param}</span>{" "}
                <span className="text-slate-500">({card.prospect.niche_exclusivity})</span>
              </p>
            ) : (
              <p className="text-slate-400">generalist</p>
            )}
            {card.evidence?.length > 0 && (
              <ul className="mt-1 space-y-0.5 text-xs text-slate-400">
                {card.evidence.map((e, k) => (
                  <li key={k}>[{e.kind}] “{e.text}” — <span className="text-slate-500">{e.url}</span></li>
                ))}
              </ul>
            )}
          </div>

          {/* message */}
          <div className="mt-4 rounded-lg bg-slate-900/70 p-3 ring-1 ring-slate-800">
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs uppercase text-slate-500">
                message · inbox {card.sending_inbox} · {card.signoff_note}
              </span>
              {!editing && (
                <button onClick={() => setEditing(true)} className="text-xs text-accent hover:underline">edit (e)</button>
              )}
            </div>
            {editing ? (
              <div className="space-y-2">
                <input value={subj} onChange={(e) => setSubj(e.target.value)} placeholder="(blank subject = threaded)"
                  className="w-full rounded bg-slate-950 px-2 py-1 text-sm ring-1 ring-slate-700" />
                <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={10}
                  className="w-full rounded bg-slate-950 px-2 py-1 text-sm ring-1 ring-slate-700" />
                <div className="flex gap-2">
                  <button onClick={doSaveEdit} disabled={busy}
                    className="rounded bg-accent/90 px-3 py-1 text-xs font-medium text-slate-900">save (⌘⏎)</button>
                  <button onClick={() => resetEdit(card)} className="rounded px-3 py-1 text-xs text-slate-400">cancel (esc)</button>
                </div>
              </div>
            ) : (
              <>
                {card.message.subject
                  ? <p className="text-sm font-medium text-slate-200">Subject: {card.message.subject}</p>
                  : card.channel === "linkedin"
                    ? null
                    : <p className="text-xs italic text-slate-500">(blank subject — threaded reply)</p>}
                <pre className="mt-1 whitespace-pre-wrap font-sans text-sm text-slate-300">{card.message.body}</pre>
              </>
            )}
          </div>

          {/* gift leads */}
          {card.gift_leads?.length > 0 && (
            <div className="mt-4">
              <p className="text-xs uppercase text-slate-500">gift leads</p>
              <div className="mt-1 grid gap-2 sm:grid-cols-2">
                {card.gift_leads.map((l, k) => <Lead key={k} lead={l} />)}
              </div>
            </div>
          )}

          {/* flags */}
          {card.flags?.length > 0 && (
            <div className="mt-4">
              <p className="text-xs uppercase text-slate-500">flags</p>
              <ul className="mt-1 space-y-0.5 text-sm text-amber-300">
                {card.flags.map((f, k) => <li key={k}>⚠ {f}</li>)}
              </ul>
            </div>
          )}

          {/* history (follow-ups) */}
          {card.history?.length > 0 && (
            <div className="mt-4">
              <p className="text-xs uppercase text-slate-500">sequence history</p>
              <div className="mt-1 space-y-2">
                {card.history.map((h, k) => (
                  <pre key={k} className="whitespace-pre-wrap rounded bg-slate-900/60 p-2 font-sans text-xs text-slate-400">{h}</pre>
                ))}
              </div>
            </div>
          )}

          {/* notes / warnings */}
          {note && (
            <div className={`mt-4 rounded-lg p-3 text-sm ${
              note.type === "error" ? "bg-rose-500/10 text-rose-300"
              : note.type === "warn" ? "bg-amber-500/10 text-amber-300" : "bg-emerald-500/10 text-emerald-300"}`}>
              {note.text}
              {note.warnings?.length > 0 && (
                <ul className="mt-1 space-y-0.5">{note.warnings.map((w, k) => <li key={k}>⚠ {w}</li>)}</ul>
              )}
            </div>
          )}

          {/* HARD send-safety gate — approve is blocked server-side until this is on */}
          <div className={`mt-4 flex items-center justify-between rounded-lg p-3 text-sm ${
            card.eligible_for_send ? "bg-emerald-500/10 text-emerald-300" : "bg-rose-500/10 text-rose-300"}`}>
            <span>
              {card.eligible_for_send
                ? "✓ eligible_for_send — approve will push"
                : "⛔ NOT eligible_for_send — approve is BLOCKED until you flip this"}
            </span>
            <button onClick={toggleEligible}
              className={`rounded px-3 py-1 text-xs font-medium ${
                card.eligible_for_send ? "bg-slate-700 text-slate-200" : "bg-rose-500/90 text-slate-900"}`}>
              {card.eligible_for_send ? "mark NOT eligible" : "mark eligible"}
            </button>
          </div>

          {/* actions */}
          <div className="mt-5 flex flex-wrap gap-2">
            <button onClick={doApprove} disabled={busy}
              className="rounded-lg bg-emerald-500/90 px-4 py-2 text-sm font-medium text-slate-900 hover:bg-emerald-400">Approve (a)</button>
            <button onClick={doReject} disabled={busy}
              className="rounded-lg bg-rose-500/90 px-4 py-2 text-sm font-medium text-slate-900 hover:bg-rose-400">Reject (r)</button>
            <button onClick={() => setEditing(true)}
              className="rounded-lg bg-slate-700 px-4 py-2 text-sm hover:bg-slate-600">Edit (e)</button>
            <button onClick={doSkip}
              className="rounded-lg bg-slate-700 px-4 py-2 text-sm hover:bg-slate-600">Skip (s)</button>
            <span className="ml-auto self-center text-xs text-slate-500">← → to move · space next</span>
          </div>
        </div>
      )}
    </div>
  );
}
