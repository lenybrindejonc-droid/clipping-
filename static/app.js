const $ = (id) => document.getElementById(id);
let pollTimer = null;
let currentId = null;

const STATUS_LABEL = {
  queued: "En attente", download: "Téléchargement", transcribe: "Transcription",
  analyze: "Analyse IA", render: "Montage", done: "Terminé", error: "Erreur",
};

const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("error").hidden = true;
  $("go").disabled = true;
  try {
    const res = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: $("url").value,
        num_clips: +$("num").value,
        min_duration: +$("min").value,
        max_duration: +$("max").value,
        layout: $("layout").value,
        subtitles: $("subs").checked,
        high_quality: $("hq").checked,
        language: $("lang").value || null,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Paramètres invalides.");
    openJob(data.id);
    loadHistory();
  } catch (err) {
    $("error").textContent = err.message;
    $("error").hidden = false;
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
  $("job-title").textContent = job.title || job.request.url;
  $("bar-fill").style.width = `${job.progress || 0}%`;
  $("job-msg").textContent = `${STATUS_LABEL[job.status] || job.status} — ${job.message || ""}`;
  const engine = $("job-engine");
  engine.hidden = !job.engine;
  engine.textContent = job.engine === "claude" ? "Sélection par Claude" : "Mode sans IA";
  const note = $("job-note");
  note.hidden = !job.engine_note;
  note.textContent = job.engine_note ? `⚠️ Claude n'a pas été utilisé : ${job.engine_note}. Les moments ont été choisis par une méthode basique, bien moins bonne.` : "";

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
  const caption = `${clip.description}\n\n${(clip.hashtags || []).map((h) => (h.startsWith("#") ? h : `#${h}`)).join(" ")}`;
  q(".caption").value = caption;
  const dl = q(".dl");
  dl.href = src;
  dl.download = `${(clip.title || "clip").replace(/[^\p{L}\p{N} _-]/gu, "").slice(0, 50)}.mp4`;
  q(".copy").addEventListener("click", async (e) => {
    await navigator.clipboard.writeText(caption);
    e.target.textContent = "Copié ✓";
    setTimeout(() => (e.target.textContent = "Copier la légende"), 1500);
  });

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
  q(".e-hook").value = clip.hook || "";
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
    q(".e-hook").value = clip.hook || "";
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
    t.textContent = job.title || job.request.url;
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
