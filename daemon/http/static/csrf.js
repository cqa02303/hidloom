"use strict";

const HIDLOOM_CSRF_COOKIE = "hidloom_csrf";
const HIDLOOM_CSRF_HEADER = "X-HIDLOOM-CSRF";

function csrfToken() {
  const prefix = `${HIDLOOM_CSRF_COOKIE}=`;
  const cookie = document.cookie
    .split("; ")
    .find(part => part.startsWith(prefix));
  if (!cookie) return "";
  return decodeURIComponent(cookie.slice(prefix.length));
}

function csrfFetch(url, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  if (!["POST", "PUT", "DELETE"].includes(method)) {
    return fetch(url, options);
  }

  const headers = new Headers(options.headers || {});
  const token = csrfToken();
  if (token) headers.set(HIDLOOM_CSRF_HEADER, token);
  return fetch(url, { ...options, headers });
}

function csrfWebSocketUrl(path) {
  const url = new URL(path, window.location.href);
  url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const token = csrfToken();
  if (token) url.searchParams.set("csrf", token);
  return url.toString();
}
