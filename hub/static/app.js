"use strict";

/* ---------------------------------------------------------------- helpers */

const app = document.getElementById("app");

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "value") el.value = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function api(path, opts = {}) {
  const headers = { "X-Requested-With": "stego", ...(opts.headers || {}) };
  let body = opts.body;
  if (body && !(body instanceof Blob) && typeof body === "object") {
    body = JSON.stringify(body);
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(path, { method: opts.method || "GET", headers, body, credentials: "same-origin" });
  if (res.status === 401 && path !== "/api/login") { state.me = null; render(); throw new Error("Session expired. Log in again."); }
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (e) { /* not json */ }
    throw new Error(msg);
  }
  if (opts.raw) return res;
  return res.json();
}

function fmtTime(ts) { return new Date(ts * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" }); }
function fmtSize(n) { return n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB"; }

function status(el, kind, text) {
  el.className = text ? `msg ${kind}` : "";
  el.textContent = text || "";
}

function download(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

async function copyText(text, btn) {
  try { await navigator.clipboard.writeText(text); } catch (e) {
    const t = h("textarea"); t.value = text; document.body.append(t); t.select(); document.execCommand("copy"); t.remove();
  }
  if (btn) { const old = btn.textContent; btn.textContent = "Copied!"; setTimeout(() => (btn.textContent = old), 1200); }
}

const progressBar = h("div");
const progressWrap = h("div", { class: "progress" }, progressBar);
hooks.progress = (f) => { progressBar.style.width = `${Math.max(0, Math.min(1, f)) * 100}%`; };

const KIND_LABELS = {
  "text": "Encrypted text",
  "img-msg": "Message hidden in image",
  "aud-msg": "Message hidden in audio",
  "aud-img": "Image hidden in audio",
  "file": "Encrypted file",
};

/* ----------------------------------------------- payload build / open (E2E) */

const utf8 = (s) => new TextEncoder().encode(s);

function baseName(name, ext) { return (name.replace(/\.[^.]+$/, "") || "file") + ext; }

async function buildPayload(kind, f) {
  const pass = f.pass;
  if (!pass || pass.length < 6) throw new Error("Passphrase must be at least 6 characters.");
  if (kind === "text") {
    if (!f.msg) throw new Error("Enter a message.");
    return { blob: new Blob([await encryptBytes(utf8(f.msg), pass)]), filename: "message.sge" };
  }
  if (kind === "img-msg") {
    if (!f.cover) throw new Error("Choose a cover image.");
    if (!f.msg) throw new Error("Enter a message.");
    return { blob: await encodeMessageInImage(f.cover, f.msg, pass), filename: baseName(f.cover.name, ".png") };
  }
  if (kind === "aud-msg") {
    if (!f.audio) throw new Error("Choose a WAV file.");
    if (!f.msg) throw new Error("Enter a message.");
    return { blob: await encodeMessageInAudio(f.audio, f.msg, pass), filename: baseName(f.audio.name, ".wav") };
  }
  if (kind === "aud-img") {
    if (!f.image || !f.audio) throw new Error("Choose an image and a WAV file.");
    return { blob: await encodeImageInAudio(f.image, f.audio, pass), filename: baseName(f.audio.name, ".wav") };
  }
  if (kind === "file") {
    if (!f.file) throw new Error("Choose a file.");
    const name = utf8(f.file.name).slice(0, 255);
    const content = new Uint8Array(await f.file.arrayBuffer());
    const plain = new Uint8Array(2 + name.length + content.length);
    plain[0] = name.length >> 8; plain[1] = name.length & 255;
    plain.set(name, 2); plain.set(content, 2 + name.length);
    return { blob: new Blob([await encryptBytes(plain, pass)]), filename: f.file.name + ".sge" };
  }
  throw new Error("Unknown type.");
}

async function openPayload(kind, blob, pass) {
  if (!pass) throw new Error("Enter the passphrase.");
  if (kind === "text") return { text: await openText(new Uint8Array(await blob.arrayBuffer()), pass) };
  if (kind === "img-msg") return { text: await decodeMessageFromImage(blob, pass) };
  if (kind === "aud-msg") return { text: await decodeMessageFromAudio(blob, pass) };
  if (kind === "aud-img") return { image: await decodeImageFromAudio(blob, pass) };
  if (kind === "file") {
    const bytes = new Uint8Array(await blob.arrayBuffer());
    if (!hasMagic(bytes)) throw new Error("This isn't an encrypted file from this tool.");
    const plain = await decryptBytes(bytes, pass);
    const n = (plain[0] << 8) | plain[1];
    return { file: new Blob([plain.slice(2 + n)]), name: new TextDecoder().decode(plain.slice(2, 2 + n)) || "file" };
  }
  throw new Error("Unknown type.");
}

function resultView(res) {
  const box = h("div");
  if (res.text != null) {
    const ta = h("textarea", { class: "out", readonly: true });
    ta.value = res.text;
    box.append(ta, h("button", { class: "btn ghost", onclick: (e) => copyText(res.text, e.target) }, "Copy"));
  }
  if (res.image) {
    const url = URL.createObjectURL(res.image);
    box.append(h("img", { src: url }), h("br"),
      h("button", { class: "btn ghost", onclick: () => download(res.image, "revealed.png") }, "Save image"));
  }
  if (res.file) {
    box.append(h("div", { class: "note" }, `File: ${res.name}`),
      h("button", { class: "btn ghost", onclick: () => download(res.file, res.name) }, "Save file"));
  }
  return box;
}

/* ------------------------------------------------------------------ state */

const state = { me: null, tab: "inbox", users: [], drops: [], unread: 0, chat: null };
let pollTimer = null;

async function boot() {
  try { state.me = await api("/api/me"); } catch (e) { state.me = null; }
  render();
}

function render() {
  closeChat();
  clearInterval(pollTimer);
  app.replaceChildren();
  if (!state.me) return app.append(loginView());
  pollTimer = setInterval(pollUnread, 20000);
  pollUnread();

  const tabs = [["inbox", "Inbox"], ["send", "Send"], ["chat", "Live chat"], ["account", "Account"]];
  if (state.me.is_admin) tabs.push(["admin", "Admin"]);
  const nav = h("nav", { class: "tabs" }, tabs.map(([id, label]) =>
    h("button", { class: state.tab === id ? "active" : "", "data-tab": id, onclick: () => { state.tab = id; render(); } },
      label, id === "inbox" && state.unread ? h("span", { class: "badge" }, state.unread) : null)));
  app.append(
    h("header", { class: "top" },
      h("div", { class: "brand" }, "\u{1F510} STEGO HUB"),
      h("div", { class: "who" }, "signed in as ", h("b", {}, state.me.username), " · ",
        h("a", { href: "#", style: "color:var(--cyan)", onclick: async (e) => { e.preventDefault(); await api("/api/logout", { method: "POST" }); state.me = null; render(); } }, "log out"))),
    nav);
  const view = h("main", {});
  app.append(view);
  ({ inbox: inboxView, send: sendView, chat: chatView, account: accountView, admin: adminView })[state.tab](view);
}

async function pollUnread() {
  try {
    const drops = await api("/api/drops");
    const n = drops.filter((d) => d.recipient === state.me.username && !d.read_at).length;
    if (n !== state.unread) {
      state.unread = n;
      const b = document.querySelector('[data-tab="inbox"]');
      if (b) { b.querySelector(".badge")?.remove(); if (n) b.append(h("span", { class: "badge" }, n)); }
    }
  } catch (e) { /* ignore */ }
}

/* ------------------------------------------------------------------ login */

function loginView() {
  const user = h("input", { autocomplete: "username", autocapitalize: "none", placeholder: "username" });
  const pass = h("input", { type: "password", autocomplete: "current-password", placeholder: "password" });
  const msg = h("div");
  const go = async (e) => {
    e.preventDefault();
    try {
      state.me = await api("/api/login", { method: "POST", body: { username: user.value, password: pass.value } });
      state.tab = "inbox";
      render();
    } catch (err) { status(msg, "err", err.message); }
  };
  return h("div", { class: "login" },
    h("div", { class: "brand" }, "\u{1F510} STEGO HUB"),
    h("p", {}, "private · end-to-end encrypted"),
    h("form", { class: "card", onsubmit: go },
      h("label", {}, "Username"), user, h("label", {}, "Password"), pass,
      h("button", { class: "btn", type: "submit" }, "Log in"), msg));
}

/* ------------------------------------------------------------------ inbox */

function inboxView(root) {
  const list = h("div", {});
  const refresh = async () => {
    try {
      state.drops = await api("/api/drops");
      state.unread = state.drops.filter((d) => d.recipient === state.me.username && !d.read_at).length;
      list.replaceChildren(...(state.drops.length ? state.drops.map(dropCard) : [h("div", { class: "note" }, "Nothing here yet. Messages sent to you show up in this list.")]));
    } catch (e) { list.replaceChildren(h("div", { class: "msg err" }, e.message)); }
  };
  root.append(
    h("div", { class: "row" }, h("h2", {}, "Inbox & sent"), h("button", { class: "btn ghost", style: "margin:0", onclick: refresh }, "Refresh")),
    list, localOpenCard());
  refresh();
}

function dropCard(d) {
  const mine = d.sender === state.me.username;
  const panel = h("div", { class: "panel hidden" });
  const card = h("div", { class: "card drop" });
  const title = h("div", {},
    h("div", { class: "title" }, mine ? `To ${d.recipient}` : `From ${d.sender}`,
      h("span", { class: "tag" }, KIND_LABELS[d.kind] || d.kind),
      !mine && !d.read_at ? h("span", { class: "new" }, "  ● NEW") : null),
    h("div", { class: "meta" }, `${fmtTime(d.created)} · ${fmtSize(d.size)} · ${d.filename}`));
  if (d.kind === "img-msg" && !mine && d.size < 6 * 1048576) {
    api(`/api/drops/${d.id}/file`, { raw: true }).then((r) => r.blob()).then((b) => {
      // carrier looks like an ordinary photo until revealed
      title.append(h("img", { class: "thumb", src: URL.createObjectURL(b) }));
    }).catch(() => {});
  }
  const pass = h("input", { type: "password", placeholder: "passphrase", autocomplete: "off" });
  const out = h("div");
  const msg = h("div");
  const reveal = async (btn) => {
    btn.disabled = true; status(msg, "", ""); out.replaceChildren();
    try {
      const blob = await (await api(`/api/drops/${d.id}/file`, { raw: true })).blob();
      const res = await openPayload(d.kind, blob, pass.value);
      out.replaceChildren(resultView(res));
    } catch (e) { status(msg, "err", e.message); }
    btn.disabled = false;
  };
  panel.append(h("div", { class: "row" }, pass, h("button", { class: "btn", style: "margin:0", onclick: (e) => reveal(e.target) }, "Reveal")), msg, out);
  const actions = h("div", { class: "row", style: "flex-wrap:nowrap" },
    !mine ? h("button", { class: "btn", style: "margin:0", onclick: () => { panel.classList.toggle("hidden"); pass.focus(); } }, "Open") : null,
    mine ? h("button", { class: "btn ghost", style: "margin:0", onclick: async () => {
      const blob = await (await api(`/api/drops/${d.id}/file`, { raw: true })).blob(); download(blob, d.filename); } }, "Download") : null,
    h("button", { class: "btn danger", style: "margin:0", onclick: async () => {
      if (!confirm("Delete this item for everyone?")) return;
      await api(`/api/drops/${d.id}`, { method: "DELETE" }); card.remove(); } }, "Delete"));
  card.append(title, actions, panel);
  return card;
}

function localOpenCard() {
  const kind = h("select", {}, Object.entries(KIND_LABELS).map(([k, v]) => h("option", { value: k }, v)));
  const file = h("input", { type: "file" });
  const pass = h("input", { type: "password", placeholder: "passphrase", autocomplete: "off" });
  const out = h("div"); const msg = h("div");
  return h("div", { class: "card" },
    h("h2", {}, "Open a file from this device"),
    h("div", { class: "note" }, "Decrypt something someone sent you outside the hub (e.g. an image from a chat app, sent as a file). Nothing is uploaded."),
    h("label", {}, "Type"), kind, h("label", {}, "File"), file, h("label", {}, "Passphrase"), pass,
    h("button", { class: "btn", onclick: async (e) => {
      e.target.disabled = true; status(msg, "", ""); out.replaceChildren();
      try {
        if (!file.files[0]) throw new Error("Choose a file.");
        out.replaceChildren(resultView(await openPayload(kind.value, file.files[0], pass.value)));
      } catch (err) { status(msg, "err", err.message); }
      e.target.disabled = false;
    } }, "Decrypt"), msg, out);
}

/* ------------------------------------------------------------------- send */

async function sendView(root) {
  try { state.users = await api("/api/users"); } catch (e) { return root.append(h("div", { class: "msg err" }, e.message)); }
  const to = h("select", {}, state.users.map((u) => h("option", { value: u.username }, u.username + (u.username === state.me.username ? " (me)" : ""))));
  const kind = h("select", {}, Object.entries(KIND_LABELS).map(([k, v]) => h("option", { value: k }, v)));
  const fields = h("div");
  const pass = h("input", { type: "password", placeholder: "shared passphrase", autocomplete: "off" });
  const msg = h("div");
  const inputs = {};

  const drawFields = () => {
    fields.replaceChildren();
    const k = kind.value;
    const add = (label, el, key) => { inputs[key] = el; fields.append(h("label", {}, label), el); };
    if (k === "img-msg") add("Cover image (any image; output is PNG)", h("input", { type: "file", accept: "image/*" }), "cover");
    if (k === "aud-msg") add("Cover audio (WAV)", h("input", { type: "file", accept: "audio/wav,.wav" }), "audio");
    if (k === "aud-img") {
      add("Image to hide", h("input", { type: "file", accept: "image/*" }), "image");
      add("Cover audio (WAV)", h("input", { type: "file", accept: "audio/wav,.wav" }), "audio");
    }
    if (k === "file") add("File to encrypt", h("input", { type: "file" }), "file");
    if (k !== "aud-img" && k !== "file") add("Message", h("textarea", { placeholder: "Secret message..." }), "msg");
    if (k === "img-msg") fields.append(h("div", { class: "note warn" }, "Recipients: the hub keeps the PNG exact. If you instead share it via WhatsApp etc., send as Document/File, never as Photo."));
  };
  kind.addEventListener("change", drawFields);
  drawFields();

  const collect = () => {
    const f = { pass: pass.value };
    for (const [k, el] of Object.entries(inputs)) f[k] = el.type === "file" ? el.files[0] : el.value;
    return f;
  };
  const run = async (btn, send) => {
    btn.disabled = true; status(msg, "", ""); progressBar.style.width = "0";
    try {
      const { blob, filename } = await buildPayload(kind.value, collect());
      if (send) {
        await api("/api/drops", { method: "POST", body: blob, headers: {
          "X-To": to.value, "X-Kind": kind.value, "X-Filename": encodeURIComponent(filename), "Content-Type": "application/octet-stream" } });
        status(msg, "ok", `Sent to ${to.value}. They need the passphrase to open it — share it outside the hub.`);
      } else {
        download(blob, filename);
        status(msg, "ok", "Saved to this device.");
      }
    } catch (e) { status(msg, "err", e.message); }
    btn.disabled = false;
  };

  root.append(h("div", { class: "card" },
    h("h2", {}, "Encrypt & send"),
    h("label", {}, "To"), to, h("label", {}, "Format"), kind, fields,
    h("label", {}, "Passphrase (never leaves this device)"), pass,
    h("div", { class: "note" }, "Encryption happens in your browser. The server only stores the result and can't read it. Tell the recipient the passphrase in person or on another channel."),
    h("button", { class: "btn", onclick: (e) => run(e.target, true) }, "Encrypt & send"),
    h("button", { class: "btn ghost", onclick: (e) => run(e.target, false) }, "Encrypt & save locally"),
    progressWrap, msg));
}

/* ------------------------------------------------------------------- chat */

function closeChat() {
  if (state.chat) { state.chat.closed = true; try { state.chat.ws.close(); } catch (e) { /* noop */ } state.chat = null; }
}

async function chatView(root) {
  let rooms = ["general"];
  try { rooms = await api("/api/rooms"); } catch (e) { /* default */ }
  const sideEl = h("div", { class: "chat-side card" });
  const mainEl = h("div", { class: "chat-main card" });
  root.append(h("div", { class: "chat-layout" }, sideEl, mainEl));

  const drawRooms = (active) => {
    const newRoom = h("input", { placeholder: "new room", maxlength: 32 });
    sideEl.replaceChildren(h("h2", {}, "Rooms"),
      ...rooms.map((r) => h("div", { class: "room" + (r === active ? " active" : ""), onclick: () => openRoom(r) }, "# " + r)),
      h("div", { style: "margin-top:10px" }, newRoom,
        h("button", { class: "btn ghost", onclick: () => {
          const n = newRoom.value.trim().toLowerCase();
          if (!/^[a-z0-9_-]{1,32}$/.test(n)) return alert("Room names: a-z 0-9 _ - (max 32)");
          if (!rooms.includes(n)) rooms.push(n);
          openRoom(n);
        } }, "Create / join")));
  };

  const openRoom = (room) => {
    closeChat();
    drawRooms(room);
    const c = state.chat = { room, ws: null, key: null, raw: [], closed: false };
    const log = h("div", { class: "chatlog" });
    const presence = h("div", { class: "presence" });
    const pass = h("input", { type: "password", placeholder: "room passphrase", autocomplete: "off",
      value: sessionStorage.getItem("chatpass:" + room) || "" });
    const note = h("div", { class: "note" });
    const input = h("input", { placeholder: "Type a message (encrypted before sending)", maxlength: 2000, autocomplete: "off" });

    const redraw = async () => {
      const frag = [];
      for (const m of c.raw) {
        let text = null;
        if (c.key) { try { text = await chatDecrypt(c.key, room, m.ct); } catch (e) { /* locked */ } }
        frag.push(text == null
          ? h("div", { class: "chatmsg locked" }, h("span", { class: "u" }, m.user), " \u{1F512} can't decrypt (wrong/missing passphrase)")
          : h("div", { class: "chatmsg" + (m.user === state.me.username ? " me" : "") },
              h("span", { class: "u" }, m.user), h("span", { class: "t" }, fmtTime(m.ts)), h("div", {}, text)));
      }
      const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 60;
      log.replaceChildren(...frag);
      if (atBottom || true) log.scrollTop = log.scrollHeight;
    };

    const setKey = async () => {
      if (!pass.value) { c.key = null; note.textContent = "Enter the room passphrase to read and send messages."; return redraw(); }
      sessionStorage.setItem("chatpass:" + room, pass.value);
      try { c.key = await deriveChatKey(pass.value, room); note.textContent = "Encrypted with your passphrase. Wrong passphrase = messages stay locked."; }
      catch (e) { note.textContent = e.message; }
      redraw();
    };

    const connect = () => {
      if (c.closed) return;
      const ws = c.ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws?room=${encodeURIComponent(room)}`);
      ws.onmessage = (ev) => {
        const d = JSON.parse(ev.data);
        if (d.type === "history") { c.raw = d.messages; redraw(); }
        else if (d.type === "msg") { c.raw.push(d); if (c.raw.length > 500) c.raw.shift(); redraw(); }
        else if (d.type === "presence") presence.textContent = "online: " + d.users.join(", ");
      };
      ws.onclose = () => { if (!c.closed) { presence.textContent = "reconnecting…"; setTimeout(connect, 2000); } };
      const ping = setInterval(() => { if (ws.readyState === 1) ws.send(JSON.stringify({ type: "ping" })); else clearInterval(ping); }, 25000);
    };

    const send = async () => {
      const text = input.value.trim();
      if (!text) return;
      if (!c.key) return (note.textContent = "Set the room passphrase first.");
      if (!c.ws || c.ws.readyState !== 1) return (note.textContent = "Not connected yet…");
      c.ws.send(JSON.stringify({ type: "msg", ct: await chatEncrypt(c.key, room, text) }));
      input.value = "";
    };

    pass.addEventListener("change", setKey);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
    mainEl.replaceChildren(h("h2", {}, "# " + room), presence, log,
      h("label", {}, "Room passphrase (never leaves this device)"), h("div", { class: "row" }, pass,
        h("button", { class: "btn ghost", style: "margin:0", onclick: setKey }, "Set")),
      note, h("div", { class: "row", style: "margin-top:10px" }, input,
        h("button", { class: "btn", style: "margin:0", onclick: send }, "Send")));
    setKey();
    connect();
  };

  drawRooms(null);
  mainEl.append(h("div", { class: "note" }, "Pick or create a room. Agree on a passphrase with the people in it; the server only ever sees ciphertext."));
}

/* ---------------------------------------------------------------- account */

function accountView(root) {
  const old = h("input", { type: "password", autocomplete: "current-password" });
  const nw = h("input", { type: "password", autocomplete: "new-password" });
  const msg = h("div");
  root.append(h("div", { class: "card" },
    h("h2", {}, "Change login password"),
    h("div", { class: "note" }, "This is your login only. Your encryption passphrases are separate and never stored on the server."),
    h("label", {}, "Current password"), old, h("label", {}, "New password (8+ chars)"), nw,
    h("button", { class: "btn", onclick: async () => {
      try { await api("/api/password", { method: "POST", body: { old: old.value, new: nw.value } }); status(msg, "ok", "Password changed."); old.value = nw.value = ""; }
      catch (e) { status(msg, "err", e.message); }
    } }, "Change password"), msg));
}

/* ------------------------------------------------------------------ admin */

async function adminView(root) {
  const body = h("tbody");
  const msg = h("div");
  const load = async () => {
    const users = await api("/api/users");
    body.replaceChildren(...users.map((u) => h("tr", {},
      h("td", {}, u.username + (u.is_admin ? " (admin)" : "")),
      h("td", {}, new Date(u.created * 1000).toLocaleDateString()),
      h("td", {}, u.username === state.me.username ? "" : [
        h("button", { class: "btn ghost", style: "margin:0 6px 0 0", onclick: async () => {
          const pw = prompt(`New password for ${u.username} (8+ chars):`);
          if (!pw) return;
          try { await api(`/api/admin/users/${u.username}/password`, { method: "POST", body: { password: pw } }); status(msg, "ok", "Password reset."); }
          catch (e) { status(msg, "err", e.message); } } }, "Reset pw"),
        h("button", { class: "btn danger", style: "margin:0", onclick: async () => {
          if (!confirm(`Delete ${u.username} and their messages?`)) return;
          await api(`/api/admin/users/${u.username}`, { method: "DELETE" }); load(); } }, "Delete")]))));
  };
  const un = h("input", { placeholder: "username", autocapitalize: "none" });
  const pw = h("input", { type: "password", placeholder: "initial password (8+)", autocomplete: "new-password" });
  const adm = h("input", { type: "checkbox", style: "width:auto" });
  root.append(
    h("div", { class: "card" }, h("h2", {}, "Users"),
      h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "User"), h("th", {}, "Created"), h("th", {}))), body)),
    h("div", { class: "card" }, h("h2", {}, "Add user"),
      h("label", {}, "Username"), un, h("label", {}, "Password"), pw,
      h("label", {}, h("span", {}, "Admin? "), adm),
      h("button", { class: "btn", onclick: async () => {
        try { await api("/api/admin/users", { method: "POST", body: { username: un.value, password: pw.value, is_admin: adm.checked } });
          status(msg, "ok", `Created ${un.value}. Give them the password privately.`); un.value = pw.value = ""; load(); }
        catch (e) { status(msg, "err", e.message); } } }, "Create user"), msg));
  load();
}

boot();
