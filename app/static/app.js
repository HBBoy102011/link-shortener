"use strict";

const TOKEN_KEY = "linkShortenerToken";

const state = {
  token: localStorage.getItem(TOKEN_KEY) || "",
  user: null,
  links: [],
  total: 0,
  page: 1,
  pageSize: 10,
  authMode: "login",
  lastShortUrl: "",
};

const $ = (id) => document.getElementById(id);

const dateFormat = new Intl.DateTimeFormat("ru-RU", {
  dateStyle: "short",
  timeStyle: "short",
});

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : dateFormat.format(date);
}

function toast(message, isError = false) {
  const node = document.createElement("div");
  node.className = "toast" + (isError ? " error" : "");
  node.textContent = message;
  $("toasts").append(node);
  window.setTimeout(() => node.remove(), 4200);
}

async function api(path, { method = "GET", body = null, auth = false } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== null) headers["Content-Type"] = "application/json";
  if (auth && state.token) headers.Authorization = `Bearer ${state.token}`;

  const response = await fetch(path, {
    method,
    headers,
    body: body === null ? undefined : JSON.stringify(body),
  });

  if (response.status === 204) return null;

  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : null;

  if (!response.ok) {
    const error = (data && data.error) || { message: `HTTP ${response.status}` };
    const failure = new Error(error.message || "Запрос не удался");
    failure.code = error.code;
    failure.status = response.status;
    failure.details = error.details;
    throw failure;
  }
  return data;
}

/* ------------------------------------------------------------------ */
/* Session                                                             */
/* ------------------------------------------------------------------ */

function renderAccount() {
  const box = $("account");
  if (state.user) {
    box.innerHTML = `
      <span title="${escapeHtml(state.user.email)}">${escapeHtml(state.user.email)}</span>
      <button id="logout-button" class="ghost small" type="button">Выйти</button>
    `;
    $("logout-button").addEventListener("click", logout);
  } else {
    box.innerHTML = '<button id="login-button" class="ghost" type="button">Войти</button>';
    $("login-button").addEventListener("click", () => openAuth("login"));
  }
  $("dashboard").classList.toggle("hidden", !state.user);
}

async function restoreSession() {
  renderAccount();
  if (!state.token) return;
  try {
    state.user = await api("/api/auth/me", { auth: true });
    renderAccount();
    await loadLinks(1);
  } catch {
    clearSession();
  }
}

function setSession(token, user) {
  state.token = token;
  state.user = user;
  localStorage.setItem(TOKEN_KEY, token);
  renderAccount();
}

function clearSession() {
  state.token = "";
  state.user = null;
  state.links = [];
  state.total = 0;
  state.page = 1;
  localStorage.removeItem(TOKEN_KEY);
  renderAccount();
  renderLinks();
}

function logout() {
  clearSession();
  toast("Вы вышли из аккаунта");
}

/* ------------------------------------------------------------------ */
/* Create link                                                         */
/* ------------------------------------------------------------------ */

function showResult(link) {
  state.lastShortUrl = link.short_url;
  $("result-short").textContent = link.short_url;
  $("result-short").href = link.short_url;
  $("result-open").href = link.short_url;
  $("result-original").textContent = link.original_url;
  $("result-qr").src = `${link.qr_url}?size=8`;

  const flags = [`код ${link.code}`];
  if (link.has_password) flags.push("защищена паролем");
  if (link.expires_at) flags.push(`истекает ${formatDate(link.expires_at)}`);
  $("result-flags").innerHTML = flags
    .map((text) => `<span class="flag">${escapeHtml(text)}</span>`)
    .join("");
  $("result").classList.remove("hidden");
}

async function onCreate(event) {
  event.preventDefault();
  const url = $("url-input").value.trim();
  if (!url) {
    toast("Вставьте ссылку", true);
    return;
  }

  const payload = { url };
  const code = $("code-input").value.trim();
  if (code) payload.custom_code = code;
  const expires = $("expires-input").value;
  if (expires) payload.expires_at = new Date(expires).toISOString();
  const password = $("password-input").value;
  if (password) payload.password = password;

  const button = $("create-button");
  button.disabled = true;
  button.textContent = "Сокращаем…";
  try {
    let link;
    try {
      link = await api("/api/links", { method: "POST", body: payload, auth: Boolean(state.token) });
    } catch (error) {
      if (error.status === 401 && state.token) {
        clearSession();
        link = await api("/api/links", { method: "POST", body: payload });
      } else {
        throw error;
      }
    }
    showResult(link);
    $("url-input").value = "";
    $("code-input").value = "";
    $("expires-input").value = "";
    $("password-input").value = "";
    toast("Короткая ссылка готова");
    if (state.user) await loadLinks(1);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Сократить";
  }
}

async function copyShortLink(url) {
  try {
    await navigator.clipboard.writeText(url);
    toast("Скопировано");
  } catch {
    const helper = document.createElement("textarea");
    helper.value = url;
    document.body.append(helper);
    helper.select();
    document.execCommand("copy");
    helper.remove();
    toast("Скопировано");
  }
}

/* ------------------------------------------------------------------ */
/* Dashboard                                                           */
/* ------------------------------------------------------------------ */

function renderLinks() {
  const body = $("links-body");
  const empty = $("links-empty");
  if (!state.user) {
    body.innerHTML = "";
    return;
  }
  empty.classList.toggle("hidden", state.links.length > 0);
  body.innerHTML = state.links
    .map((link) => {
      const flags = [];
      if (link.has_password) flags.push("🔒");
      if (link.expires_at) flags.push(`⏳ ${formatDate(link.expires_at)}`);
      return `
        <tr>
          <td class="short"><a href="${escapeHtml(link.short_url)}" target="_blank" rel="noreferrer">${escapeHtml(link.code)}</a></td>
          <td class="original" title="${escapeHtml(link.original_url)}">${escapeHtml(link.original_url)}</td>
          <td class="num">${link.clicks}</td>
          <td>${formatDate(link.created_at)}${flags.length ? `<br /><small>${escapeHtml(flags.join(" "))}</small>` : ""}</td>
          <td>
            <div class="row-actions">
              <button class="ghost small" data-action="stats" data-id="${link.id}" type="button">Статистика</button>
              <button class="ghost small" data-action="copy" data-id="${link.id}" type="button">Копировать</button>
              <button class="danger small" data-action="delete" data-id="${link.id}" type="button">Удалить</button>
            </div>
          </td>
        </tr>`;
    })
    .join("");

  const pages = Math.max(1, Math.ceil(state.total / state.pageSize));
  $("page-info").textContent = `Страница ${state.page} из ${pages} · всего ${state.total}`;
  $("prev-page").disabled = state.page <= 1;
  $("next-page").disabled = state.page >= pages;
}

async function loadLinks(page = state.page) {
  if (!state.user) return;
  try {
    const data = await api(`/api/links?page=${page}&page_size=${state.pageSize}`, { auth: true });
    state.links = data.items;
    state.total = data.total;
    state.page = data.page;
    renderLinks();
  } catch (error) {
    toast(error.message, true);
  }
}

async function onLinkAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button || !state.user) return;
  const id = Number(button.dataset.id);
  const link = state.links.find((item) => item.id === id);
  if (!link) return;

  if (button.dataset.action === "copy") {
    await copyShortLink(link.short_url);
    return;
  }
  if (button.dataset.action === "stats") {
    await openStats(link);
    return;
  }
  if (button.dataset.action === "delete") {
    const confirmed = window.confirm(`Удалить ${link.short_url}? Статистика тоже исчезнет.`);
    if (!confirmed) return;
    try {
      await api(`/api/links/${id}`, { method: "DELETE", auth: true });
      if (state.links.length === 1 && state.page > 1) state.page -= 1;
      await loadLinks(state.page);
      toast("Ссылка удалена");
    } catch (error) {
      toast(error.message, true);
    }
  }
}

/* ------------------------------------------------------------------ */
/* Stats dialog                                                        */
/* ------------------------------------------------------------------ */

async function openStats(link) {
  const dialog = $("stats-dialog");
  $("stats-link").textContent = link.short_url;
  $("stat-total").textContent = "…";
  $("stat-unique").textContent = "…";
  $("stat-last").textContent = "…";
  $("stats-days").innerHTML = "";
  $("stats-referers").innerHTML = "";
  $("stats-devices").innerHTML = "";
  if (!dialog.open) dialog.showModal();

  try {
    const stats = await api(`/api/links/${link.id}/stats`, { auth: true });
    $("stat-total").textContent = stats.total_clicks;
    $("stat-unique").textContent = stats.unique_visitors;
    $("stat-last").textContent = formatDate(stats.last_click_at);

    const maximum = Math.max(1, ...stats.days.map((day) => day.clicks));
    $("stats-days").innerHTML = stats.days
      .map((day) => {
        const height = day.clicks === 0 ? 2 : Math.round((day.clicks / maximum) * 100);
        return `<div class="bar" data-value="${day.clicks}" style="height:${height}%"
          data-label="${escapeHtml(day.date)}: ${day.clicks}"></div>`;
      })
      .join("");

    renderStatList("stats-referers", stats.referers, "source");
    renderStatList("stats-devices", stats.devices, "device");
  } catch (error) {
    toast(error.message, true);
    dialog.close();
  }
}

function renderStatList(target, rows, key) {
  const list = $(target);
  if (!rows.length) {
    list.innerHTML = '<li><span>Пока нет данных</span></li>';
    return;
  }
  list.innerHTML = rows
    .map(
      (row) =>
        `<li><span>${escapeHtml(row[key])}</span><span class="count">${row.clicks}</span></li>`,
    )
    .join("");
}

/* ------------------------------------------------------------------ */
/* Auth dialog                                                         */
/* ------------------------------------------------------------------ */

function openAuth(mode = "login") {
  state.authMode = mode;
  const dialog = $("auth-dialog");
  updateAuthMode();
  $("auth-form").reset();
  if (!dialog.open) dialog.showModal();
  $("auth-email").focus();
}

function updateAuthMode() {
  const isLogin = state.authMode === "login";
  $("auth-title").textContent = isLogin ? "Вход" : "Регистрация";
  $("auth-submit").textContent = isLogin ? "Войти" : "Создать аккаунт";
  $("tab-login").classList.toggle("active", isLogin);
  $("tab-register").classList.toggle("active", !isLogin);
  $("auth-password").setAttribute("autocomplete", isLogin ? "current-password" : "new-password");
  $("auth-password").minLength = isLogin ? 1 : 8;
}

async function onAuthSubmit(event) {
  event.preventDefault();
  const email = $("auth-email").value.trim();
  const password = $("auth-password").value;
  if (!email || !password) {
    toast("Заполните e-mail и пароль", true);
    return;
  }
  const path = state.authMode === "login" ? "/api/auth/login" : "/api/auth/register";
  const button = $("auth-submit");
  button.disabled = true;
  try {
    const data = await api(path, { method: "POST", body: { email, password } });
    setSession(data.access_token, data.user);
    $("auth-dialog").close();
    toast(state.authMode === "login" ? "С возвращением" : "Аккаунт создан");
    await loadLinks(1);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

/* ------------------------------------------------------------------ */
/* Wiring                                                              */
/* ------------------------------------------------------------------ */

function init() {
  $("origin-label").textContent = `${window.location.origin}/`;
  $("create-form").addEventListener("submit", onCreate);
  $("copy-button").addEventListener("click", () => copyShortLink(state.lastShortUrl));
  $("refresh-button").addEventListener("click", () => loadLinks(state.page));
  $("prev-page").addEventListener("click", () => loadLinks(Math.max(1, state.page - 1)));
  $("next-page").addEventListener("click", () => loadLinks(state.page + 1));
  $("links-body").addEventListener("click", onLinkAction);

  $("auth-form").addEventListener("submit", onAuthSubmit);
  $("auth-cancel").addEventListener("click", () => $("auth-dialog").close());
  $("tab-login").addEventListener("click", () => {
    state.authMode = "login";
    updateAuthMode();
  });
  $("tab-register").addEventListener("click", () => {
    state.authMode = "register";
    updateAuthMode();
  });
  $("stats-close").addEventListener("click", () => $("stats-dialog").close());

  restoreSession();
}

document.addEventListener("DOMContentLoaded", init);
