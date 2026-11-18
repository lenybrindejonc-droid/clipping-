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
  if (!["done", "error"].includes(job.status)) pollTimer = setTimeout(poll, 1500);
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
    if (container.children[i]) return;
    const node = $("clip-tpl").content.cloneNode(true);
    const src = `/media/${job.id}/${clip.file}`;
    const video = node.querySelector("video");
    video.src = src;
    video.poster = `/media/${job.id}/${clip.thumb}`;
    node.querySelector(".score").textContent = `🔥 ${clip.virality_score}/100`;
    node.querySelector(".time").textContent = `${fmt(clip.start)} → ${fmt(clip.end)} · ${Math.round(clip.duration)}s`;
    node.querySelector(".title").textContent = clip.title;
    node.querySelector(".reason").textContent = clip.reason;
    const caption = `${clip.description}\n\n${(clip.hashtags || []).map((h) => (h.startsWith("#") ? h : `#${h}`)).join(" ")}`;
    node.querySelector(".caption").value = caption;
    const dl = node.querySelector(".dl");
    dl.href = src;
    dl.download = `${(clip.title || "clip").replace(/[^\p{L}\p{N} _-]/gu, "").slice(0, 50)}.mp4`;
    node.querySelector(".copy").addEventListener("click", async (e) => {
      await navigator.clipboard.writeText(caption);
      e.target.textContent = "Copié ✓";
      setTimeout(() => (e.target.textContent = "Copier la légende"), 1500);
    });
    container.appendChild(node);
  });
}

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
