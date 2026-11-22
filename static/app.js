const $ = (id) => document.getElementById(id);
let pollTimer = null;
let currentId = null;

const STATUS_LABEL = {
  queued: "En attente", download: "Téléchargement", transcribe: "Transcription",
  analyze: "Analyse IA", render: "Montage", done: "Terminé", error: "Erreur",
};

const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function params() {
  return {
    num_clips: +$("num").value,
    min_duration: +$("min").value,
    max_duration: +$("max").value,
    layout: $("layout").value,
    content_type: $("type").value,
    facecam: $("facecam").value,
    streamer: $("streamer").value,
    jeu: $("jeu").value,
    rules: $("rules").value,
    subtitles: $("subs").checked,
    show_hook: $("hook").checked,
    zoom: $("zoom").checked,
    high_quality: $("hq").checked,
    language: $("lang").value || null,
  };
}

// Vérifie les réglages AVANT d'envoyer le fichier (sinon on envoie pour rien)
function checkParams() {
  const p = params();
  if (!(p.num_clips >= 1 && p.num_clips <= 30)) return "Nombre de clips : choisis une valeur entre 1 et 30.";
  if (!(p.min_duration >= 5 && p.min_duration <= 120)) return "Durée minimum : entre 5 et 120 secondes.";
  if (!(p.max_duration >= 10 && p.max_duration <= 180)) return "Durée maximum : entre 10 et 180 secondes.";
  if (p.min_duration >= p.max_duration) return "La durée minimum doit être inférieure à la durée maximum.";
  return null;
}

function showError(msg) {
  $("error").textContent = msg;
  $("error").hidden = false;
}

// --- Envoi d'un fichier depuis l'ordinateur
$("file").addEventListener("change", () => {
  const f = $("file").files[0];
  $("file-name").hidden = !f;
  $("send-file").hidden = !f;
  if (f) $("file-name").textContent = `${f.name} — ${(f.size / 1048576).toFixed(0)} Mo`;
});

const CHUNK_MAX = 8 * 1024 * 1024;       // 8 Mo par morceau quand tout va bien
const CHUNK_MIN = 2 * 1024 * 1024;       // réduit à 2 Mo si la connexion flanche
const ESSAIS = 6;                        // essais par morceau avant de souffler
const REPRISES = 3;                      // reprises automatiques avant d'abandonner
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let envoi = null;                        // { id, file } de l'envoi en cours

function majEnvoi(recu, total, suffixe = "") {
  const pct = (recu / total) * 100;
  $("up-fill").style.width = `${pct}%`;
  $("file-name").textContent =
    `Envoi… ${pct.toFixed(0)} % (${(recu / 1048576).toFixed(0)} / ${(total / 1048576).toFixed(0)} Mo)${suffixe}`;
}

async function envoyerMorceaux(id, file, depuis) {
  let offset = depuis;
  let taille = CHUNK_MAX;
  while (offset < file.size) {
    const bout = file.slice(offset, offset + taille);
    let envoye = false;
    for (let essai = 1; essai <= ESSAIS && !envoye; essai++) {
      try {
        const r = await fetch(`/api/uploads/${id}?offset=${offset}`, { method: "PUT", body: bout });
        const d = await r.json().catch(() => ({}));
        if (r.ok || r.status === 409) {        // 409 = on reprend à la position du serveur
          offset = d.received ?? offset;
          envoye = true;
        } else if (r.status === 400 || r.status === 404) {
          throw new Error(d.detail || "Envoi refusé.");
        }
      } catch (err) {
        if (err.message && !err.message.includes("Failed to fetch")) throw err;
      }
      if (!envoye) {
        taille = CHUNK_MIN;                    // connexion fragile : on envoie plus petit
        majEnvoi(offset, file.size, ` — reprise (essai ${essai}/${ESSAIS})`);
        await sleep(Math.min(3000 * essai, 20000));
      }
    }
    if (!envoye) throw new Error("coupure");
    majEnvoi(offset, file.size);
  }
}

async function demarrerEnvoi(file, reprise = false) {
  $("error").hidden = true;
  $("send-file").disabled = true;
  $("resume-file").hidden = true;
  $("up-bar").hidden = false;
  try {
    if (!reprise || !envoi) {
      const r = await fetch("/api/uploads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name, size: file.size, params: params() }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Envoi impossible.");
      envoi = { id: d.upload_id, file };
    }
    for (let tentative = 1; ; tentative++) {
      const etat = await (await fetch(`/api/uploads/${envoi.id}`)).json();
      try {
        await envoyerMorceaux(envoi.id, file, etat.received || 0);
        break;
      } catch (err) {
        if (err.message !== "coupure" || tentative >= REPRISES) throw err;
        majEnvoi(etat.received || 0, file.size, " — connexion perdue, nouvelle tentative…");
        await sleep(10000);                   // on laisse la connexion revenir
      }
    }

    $("file-name").textContent = "Envoi terminé ✓ — vérification…";
    const fin = await fetch(`/api/uploads/${envoi.id}/finish`, { method: "POST" });
    const job = await fin.json();
    if (!fin.ok) throw new Error(typeof job.detail === "string" ? job.detail : "Fichier refusé.");
    envoi = null;
    $("up-bar").hidden = true;
    $("up-fill").style.width = "0%";
    $("file-name").textContent = "Envoi terminé ✓";
    openJob(job.id);
    loadHistory();
  } catch (err) {
    $("up-bar").hidden = true;
    if (err.message === "coupure") {
      showError("Connexion interrompue. Rien n'est perdu : clique sur « Reprendre l'envoi ».");
      $("resume-file").hidden = false;
    } else {
      showError(err.message);
      envoi = null;
    }
  } finally {
    $("send-file").disabled = false;
  }
}

$("send-file").addEventListener("click", () => {
  const f = $("file").files[0];
  if (!f) return;
  const probleme = checkParams();
  if (probleme) { showError(probleme); return; }   // on n'envoie pas le fichier pour rien
  envoi = null;
  demarrerEnvoi(f);
});

$("resume-file").addEventListener("click", () => {
  const f = $("file").files[0];
  if (f) demarrerEnvoi(f, true);
});

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const probleme = checkParams();
  if (probleme) { showError(probleme); return; }
  $("error").hidden = true;
  $("go").disabled = true;
  try {
    const res = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: $("url").value, ...params() }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Paramètres invalides.");
    openJob(data.id);
    loadHistory();
  } catch (err) {
    showError(err.message);
  } finally {
    $("go").disabled = false;
  }
});

function openJob(id) {
  currentId = id;
  history.replaceState(null, "", `#${id}`);
  $("clips").innerHTML = "";
  $("current").hidden = false;
  clearTimeout(pollTimer);
  poll();
}

async function poll() {
  const id = currentId;
  const res = await fetch(`/api/jobs/${id}`);
  if (!res.ok) { $("current").hidden = true; return; }
  const job = await res.json();
  if (id !== currentId) return;
  render(job);
  const busy = job.clips.some((c) => c.rendering);
  if (!["done", "error"].includes(job.status) || busy) pollTimer = setTimeout(poll, 1500);
  else loadHistory();
}

function render(job) {
  $("job-title").textContent = job.title || job.request.url || "Vidéo envoyée";
  $("bar-fill").style.width = `${job.progress || 0}%`;
  $("job-msg").textContent = `${STATUS_LABEL[job.status] || job.status} — ${job.message || ""}`;
  const engine = $("job-engine");
  engine.hidden = !job.engine;
  engine.textContent = job.engine === "claude" ? "Sélection par Claude" : "Mode sans IA";
  const note = $("job-note");
  note.hidden = !job.engine_note;
  note.textContent = job.engine_note ? `⚠️ Claude n'a pas été utilisé : ${job.engine_note}. Les moments ont été choisis par une méthode basique, bien moins bonne.` : "";

  const cancel = $("cancel-job");
  cancel.hidden = job.status !== "queued";
  cancel.onclick = async () => {
    cancel.disabled = true;
    const res = await fetch(`/api/jobs/${job.id}`, { method: "DELETE" });
    if (res.ok) { clearTimeout(pollTimer); $("current").hidden = true; history.replaceState(null, "", "#"); loadHistory(); }
    else { alert((await res.json()).detail || "Annulation impossible."); cancel.disabled = false; }
  };

  const zip = $("zip-all");
  zip.hidden = !(job.status === "done" && job.clips.length);
  zip.href = `/api/jobs/${job.id}/zip`;

  const container = $("clips");
  job.clips.forEach((clip, i) => {
    const sig = `${clip.version || 1}|${clip.rendering || ""}|${clip.error || ""}`;
    const existing = container.children[i];
    if (existing && existing.dataset.sig === sig) return;
    const card = buildCard(job, clip, i);
    card.dataset.sig = sig;
    if (existing) existing.replaceWith(card);
    else container.appendChild(card);
  });
}

function buildCard(job, clip, i) {
  const node = $("clip-tpl").content.firstElementChild.cloneNode(true);
  const q = (sel) => node.querySelector(sel);
  const v = clip.version || 1;
  const src = `/media/${job.id}/${clip.file}?v=${v}`;
  const video = q("video");
  video.src = src;
  video.poster = `/media/${job.id}/${clip.thumb}?v=${v}`;
  q(".score").textContent = `🔥 ${clip.virality_score}/100`;
  q(".time").textContent = `${fmt(clip.start)} → ${fmt(clip.end)} · ${Math.round(clip.duration)}s`;
  q(".title").textContent = clip.title;
  q(".reason").textContent = clip.reason;
  if (clip.kind) { q(".kind").hidden = false; q(".kind").textContent = clip.kind; }
  if (clip.spoiler) q(".spoiler").hidden = false;
  // --- Légendes par plateforme
  const legendes = clip.captions || {};
  const hashtags = (clip.hashtags || []).map((h) => (h.startsWith("#") ? h : `#${h}`)).join(" ");
  const parDefaut = `${clip.description || ""}\n\n${hashtags}`.trim();
  let plateforme = "tiktok";
  const majLegende = () => { q(".caption").value = legendes[plateforme] || parDefaut; };
  if (legendes.tiktok) {
    q(".plateformes").hidden = false;
    q(".plateformes").querySelectorAll(".chip").forEach((c) =>
      c.addEventListener("click", () => {
        plateforme = c.dataset.p;
        q(".plateformes").querySelectorAll(".chip").forEach((x) => x.classList.toggle("actif", x === c));
        majLegende();
      }));
  }
  majLegende();

  const dl = q(".dl");
  dl.href = src;
  dl.download = `${(clip.title || "clip").replace(/[^\p{L}\p{N} _-]/gu, "").slice(0, 50)}.mp4`;
  q(".copy").addEventListener("click", async (e) => {
    await navigator.clipboard.writeText(q(".caption").value);
    e.target.textContent = "Copié ✓";
    setTimeout(() => (e.target.textContent = "Copier la légende"), 1500);
  });

  // --- Accroches proposées
  const accroches = clip.hooks && clip.hooks.length ? clip.hooks
    : (clip.hook ? [{ texte: clip.hook, pourquoi: "" }] : []);
  if (accroches.length) {
    q(".hooks").hidden = false;
    accroches.forEach((h) => {
      const ligne = document.createElement("div");
      ligne.className = "hook-ligne";

      const b = document.createElement("button");
      b.type = "button";
      b.className = "hook-chip";
      b.innerHTML = `<b></b><span class="muted small"></span>`;
      b.querySelector("b").textContent = h.texte;
      b.querySelector("span").textContent = [h.style, h.pourquoi].filter(Boolean).join(" — ");
      b.title = "Copier cette accroche";
      b.addEventListener("click", async () => {
        await navigator.clipboard.writeText(h.texte);
        const champ = q(".e-hook");
        if (champ) champ.value = h.texte;
        b.classList.add("copie");
        setTimeout(() => b.classList.remove("copie"), 1500);
      });

      const poser = document.createElement("button");
      poser.type = "button";
      poser.className = "btn ghost poser";
      poser.textContent = "🎬 Sur la vidéo";
      poser.title = "Refaire ce clip avec cette accroche incrustée";
      poser.addEventListener("click", async () => {
        poser.disabled = true;
        poser.textContent = "Montage…";
        const res = await fetch(`/api/jobs/${job.id}/clips/${i}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            start: clip.start, end: clip.end, hook: h.texte,
            layout: clip.layout || job.request.layout || "auto", text: null,
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok) {
          render(data);
          clearTimeout(pollTimer);
          pollTimer = setTimeout(poll, 1500);
        } else {
          alert(typeof data.detail === "string" ? data.detail : "Montage impossible.");
          poser.disabled = false;
          poser.textContent = "🎬 Sur la vidéo";
        }
      });

      ligne.append(b, poser);
      q(".hooks-list").appendChild(ligne);
    });
    if (clip.hook_on_video) {
      const info = document.createElement("p");
      info.className = "muted small";
      info.textContent = `Accroche actuellement sur la vidéo : « ${clip.hook_on_video} »`;
      q(".hooks").appendChild(info);
    }
  }

  // --- Vérification des règles de campagne
  const verif = clip.campaign_check || [];
  if (verif.length) {
    q(".verif").hidden = false;
    const icones = { ok: "✅", probleme: "⛔", incertain: "❓" };
    verif.forEach((v) => {
      const li = document.createElement("li");
      li.textContent = `${icones[v.verdict] || "❓"} ${v.regle} — ${v.detail}`;
      q(".verif-list").appendChild(li);
    });
    const souci = verif.some((v) => v.verdict !== "ok");
    q(".verif").querySelector("summary").textContent =
      souci ? "⚠️ Règles de campagne : à vérifier" : "✅ Règles de campagne : tout est bon";
  }

  if (clip.error) {
    q(".clip-error").hidden = false;
    q(".clip-error").textContent = `⚠️ La modification a échoué : ${clip.error}`;
  }
  if (clip.rendering) {
    q(".busy").hidden = false;
    q(".busy-msg").textContent = clip.rendering;
    q(".edit-toggle").disabled = true;
    return node;
  }

  // --- Avis sur le clip (sert à améliorer les prochains lots)
  const envoyerAvis = async (verdict, raison = "", note = "") => {
    const r = await fetch(`/api/jobs/${job.id}/clips/${i}/avis`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ verdict, raison, note }),
    });
    const d = await r.json().catch(() => ({}));
    q(".avis").hidden = true;
    q(".avis-detail").hidden = true;
    q(".avis-merci").hidden = false;
    q(".avis-merci").textContent = r.ok ? d.message : "Avis non enregistré.";
  };
  if (clip.avis) {
    q(".avis").hidden = true;
    q(".avis-merci").hidden = false;
    q(".avis-merci").textContent = clip.avis === "bon" ? "👍 noté comme bon" : "👎 noté";
  }
  q(".vote-bon").addEventListener("click", () => envoyerAvis("bon"));
  q(".vote-mauvais").addEventListener("click", () => {
    q(".avis").hidden = true;
    q(".avis-detail").hidden = false;
  });
  q(".avis-detail").addEventListener("submit", (e) => {
    e.preventDefault();
    envoyerAvis("mauvais", q(".avis-raison").value, q(".avis-note").value);
  });

  // --- Éditeur
  const editor = q(".editor");
  const state = { start: clip.start, end: clip.end };
  const maxEnd = job.duration || clip.end + 600;
  const show = () => {
    q(".t-start").textContent = fmt1(state.start);
    q(".t-end").textContent = fmt1(state.end);
    q(".t-dur").textContent = `Durée : ${Math.round(state.end - state.start)} s`;
  };
  q(".edit-toggle").addEventListener("click", () => {
    editor.hidden = !editor.hidden;
    q(".edit-toggle").textContent = editor.hidden ? "✏️ Modifier" : "Fermer l'éditeur";
  });
  q(".e-hook").value = clip.hook_on_video || "";
  q(".e-text").value = clip.text || "";
  q(".e-layout").value = clip.layout || job.request.layout || "auto";
  editor.querySelectorAll(".step").forEach((b) =>
    b.addEventListener("click", () => {
      const f = b.dataset.field;
      const next = +(state[f] + +b.dataset.delta).toFixed(2);
      if (f === "start" && (next < 0 || state.end - next < 3)) return;
      if (f === "end" && (next > maxEnd || next - state.start < 3)) return;
      state[f] = next;
      show();
    }),
  );
  q(".cancel").addEventListener("click", () => {
    state.start = clip.start; state.end = clip.end;
    q(".e-hook").value = clip.hook_on_video || "";
    q(".e-text").value = clip.text || "";
    show();
    editor.hidden = true;
    q(".edit-toggle").textContent = "✏️ Modifier";
  });
  editor.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = editor.querySelector("[type=submit]");
    btn.disabled = true;
    const textChanged = q(".e-text").value.trim() !== (clip.text || "").trim();
    try {
      const res = await fetch(`/api/jobs/${job.id}/clips/${i}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          start: state.start, end: state.end, hook: q(".e-hook").value, layout: q(".e-layout").value,
          // texte envoyé seulement s'il a été corrigé (sinon il suit les nouvelles bornes)
          text: textChanged ? q(".e-text").value : null,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Modification impossible.");
      render(data);
      clearTimeout(pollTimer);
      pollTimer = setTimeout(poll, 1500);
    } catch (err) {
      alert(err.message);
      btn.disabled = false;
    }
  });
  show();
  return node;
}

const fmt1 = (s) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`;

async function loadHistory() {
  const res = await fetch("/api/jobs");
  const jobs = await res.json();
  $("history-wrap").hidden = jobs.length === 0;
  const ul = $("history");
  ul.innerHTML = "";
  for (const job of jobs) {
    const li = document.createElement("li");
    const t = document.createElement("span");
    t.className = "h-title";
    t.textContent = job.title || job.request.url || "Vidéo envoyée";
    const s = document.createElement("span");
    s.className = "muted";
    s.textContent = job.status === "done" ? `${job.clips.length} clips` : STATUS_LABEL[job.status];
    li.append(t, s);
    li.addEventListener("click", () => { openJob(job.id); window.scrollTo({ top: 0, behavior: "smooth" }); });
    ul.appendChild(li);
  }
}

loadHistory();
if (location.hash.length > 1) openJob(location.hash.slice(1));

// Chaque type de contenu a ses réglages conseillés : on les applique au choix du type.
let PRESETS = {};
fetch("/api/presets").then((r) => r.json()).then((p) => { PRESETS = p; }).catch(() => {});
$("type").addEventListener("change", () => {
  const p = PRESETS[$("type").value];
  if (!p) return;
  $("num").value = p.n;
  $("min").value = p.min_d;
  $("max").value = p.max_d;
  $("layout").value = p.layout;
  $("zoom").checked = p.zoom;
  const info = $("preset-info");
  info.hidden = false;
  info.textContent =
    `Réglages conseillés pour « ${p.nom} » : ${p.n} clips de ${p.min_d} à ${p.max_d} s. Tu peux les modifier.`;
});
