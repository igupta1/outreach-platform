// Thin fetch wrapper for the operator API. The bearer token is entered once
// (token gate) and kept in localStorage; every /api call carries it.

const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export function getToken() {
  return localStorage.getItem("ui_token") || "";
}
export function setToken(t) {
  localStorage.setItem("ui_token", t);
}
export function clearToken() {
  localStorage.removeItem("ui_token");
}

async function req(path, { method = "GET", body, form } = {}) {
  const headers = { Authorization: `Bearer ${getToken()}` };
  let payload;
  if (form) {
    payload = form; // FormData — let the browser set the boundary
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(`${BASE}${path}`, { method, headers, body: payload });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = (data && data.detail) || res.statusText;
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return data;
}

export const api = {
  // H1
  uploadCsv(file, niche) {
    const form = new FormData();
    form.append("file", file);
    form.append("niche", niche);
    return req("/api/prospects/upload", { method: "POST", form });
  },
  prospects: () => req("/api/prospects"),
  setEligible: (id, eligible) =>
    req(`/api/prospects/${id}/eligible?eligible=${eligible}`, { method: "POST" }),
  // H2
  generate: (emails, linkedin, pack) =>
    req("/api/generate", { method: "POST", body: { emails, linkedin, pack } }),
  generateStatus: (jobId) => req(`/api/generate/status?job_id=${encodeURIComponent(jobId)}`),
  // H3 (channel = "email" | "linkedin")
  cards: (channel) => req(`/api/cards${channel ? `?channel=${channel}` : ""}`),
  approve: (id, message, channel = "email") =>
    req(`/api/cards/${id}/approve?channel=${channel}`, { method: "POST", body: { message: message ?? null } }),
  reject: (id, channel = "email") =>
    req(`/api/cards/${id}/reject?channel=${channel}`, { method: "POST" }),
  edit: (id, subject, body, channel = "email") =>
    req(`/api/cards/${id}/edit?channel=${channel}`, { method: "POST", body: { subject, body } }),
  skip: (id) => req(`/api/cards/${id}/skip`, { method: "POST" }),
  // H4
  linkedinQueue: () => req("/api/linkedin/queue"),
  linkedinConnection: (id, accepted) =>
    req(`/api/linkedin/${id}/connection?accepted=${accepted}`, { method: "POST" }),
  linkedinConnectSent: (id) => req(`/api/linkedin/${id}/connect_sent`, { method: "POST" }),
  linkedinSent: (id) => req(`/api/linkedin/${id}/sent`, { method: "POST" }),
};
