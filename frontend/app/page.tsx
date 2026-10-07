"use client";

import { useEffect, useState } from "react";

type Scene = {
  id: number; caption: string; narration: string; duration: number;
  visual_status: string; audio_status: string; visual_attempts: number; audio_attempts: number; error: string | null;
};
type Job = {
  id: string; title: string | null; status: string; error: string | null; running: boolean;
  scenes: Scene[]; video_url: string | null;
};

const STEPS: [string, string][] = [
  ["SCRIPTED", "Script"],
  ["SCENES_PLANNED", "Scenes"],
  ["VISUALS_GENERATED", "Visuals"],
  ["AUDIO_GENERATED", "Voice"],
  ["ASSEMBLING", "Render"],
  ["COMPLETED", "Done"],
];
const ORDER = ["CREATED", ...STEPS.map(([k]) => k)];

// Index of the last completed step. FAILED carries no stage, so infer it from per-scene state.
function progress(job: Job): number {
  if (job.status !== "FAILED") return ORDER.indexOf(job.status);
  if (job.scenes.length === 0) return 0;
  if (!job.scenes.every((s) => s.visual_status === "GENERATED")) return ORDER.indexOf("SCENES_PLANNED");
  if (!job.scenes.every((s) => s.audio_status === "GENERATED")) return ORDER.indexOf("VISUALS_GENERATED");
  return ORDER.indexOf("AUDIO_GENERATED");
}

const EXAMPLES = [
  "Create a 30-second promotional video for an AI recruiting platform",
  "Create a 20-second personalized birthday greeting for Rahul",
  "Create a 15-second teaser for a meditation app",
];

async function api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method, headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export default function Home() {
  const [prompt, setPrompt] = useState(EXAMPLES[0]);
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const active = !!job && (job.running || !["COMPLETED", "FAILED"].includes(job.status));
  const failed = job?.status === "FAILED";

  useEffect(() => {
    if (!job || !active) return;
    const t = setInterval(async () => {
      try { setJob(await api<Job>(`/api/videos/${job.id}`)); } catch (e) { setErr(String(e)); }
    }, 1500);
    return () => clearInterval(t);
  }, [job?.id, active]);

  const run = async (fn: () => Promise<Job>) => {
    setErr(null);
    try { setJob(await fn()); } catch (e) { setErr(String(e)); }
  };

  return (
    <main>
      <div className="brand">
        <div className="logo">🎬</div>
        <div>
          <h1>AgentVideoForge</h1>
          <p className="sub">Prompt → Director → Visuals + Voice → Editor → MP4</p>
        </div>
      </div>

      <section className="panel">
        <h2>Describe your video</h2>
        <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Create a 30-second video about…" />
        <div className="chips">
          {EXAMPLES.map((ex) => (
            <button key={ex} className="chip" onClick={() => setPrompt(ex)}>{ex.replace("Create a ", "")}</button>
          ))}
        </div>
        <div className="row">
          <span className="hint">{prompt.length}/1000 · mention a length like “30-second”</span>
          <button className="primary" disabled={active || prompt.trim().length < 5}
            onClick={() => run(() => api<Job>("/api/videos", "POST", { prompt }))}>
            {active ? "Generating…" : "Generate video"}
          </button>
        </div>
        {err && <div className="err">{err}</div>}
      </section>

      {job && (
        <section className="panel">
          <h2>Pipeline{job.title ? ` · ${job.title}` : ""}</h2>
          <div className="stepper">
            {STEPS.map(([key, label]) => {
              const cur = progress(job), mine = ORDER.indexOf(key);
              const cls = mine <= cur ? "done" : mine === cur + 1 ? (failed ? "bad" : "cur") : "";
              return (
                <div key={key} className={`step ${cls}`}>
                  <div className="bar" />
                  <div className="lbl">{label}</div>
                </div>
              );
            })}
          </div>

          {failed && (
            <>
              <div className="err">{job.error}</div>
              <div style={{ marginTop: 12 }}>
                <button className="primary" onClick={() => run(() => api<Job>(`/api/videos/${job.id}/retry`, "POST"))}>
                  Retry failed work
                </button>
              </div>
            </>
          )}

          {job.scenes.length > 0 && (
            <div className="scenes">
              {job.scenes.map((s) => (
                <div className="scene" key={s.id}>
                  <div className="thumb">
                    {s.visual_status === "GENERATED"
                      ? <img src={`/api/videos/${job.id}/scenes/${s.id}/image.png`} alt={s.caption} />
                      : <div className="shimmer" />}
                    <span className="num">Scene {s.id}</span>
                    <span className="dur">{s.duration.toFixed(1)}s</span>
                  </div>
                  <div className="sbody">
                    <div className="cap">{s.caption}</div>
                    <div className="nar">{s.narration}</div>
                    <div className="tags">
                      <span className={`tag ${s.visual_status}`}>visual</span>
                      <span className={`tag ${s.audio_status}`}>voice</span>
                      {!active && (
                        <button className="ghost"
                          onClick={() => run(() => api<Job>(`/api/videos/${job.id}/scenes/${s.id}/retry`, "POST"))}>
                          Regenerate
                        </button>
                      )}
                    </div>
                    {s.error && <div className="err">{s.error.slice(0, 140)}</div>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {job?.video_url && (
        <section className="panel">
          <h2>Final video</h2>
          <video key={job.video_url + job.status} src={job.video_url} controls />
          <a className="dl" href={job.video_url} download="final.mp4">⬇ Download final.mp4</a>
        </section>
      )}
    </main>
  );
}
