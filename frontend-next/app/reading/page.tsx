"use client";

import { useEffect, useRef, useState } from "react";
import { api, API_BASE, getToken } from "@/lib/api";
import { to16k } from "@/lib/audio";
import { LEVEL_NAMES, type ReadingPassage, type ReadingResult } from "@/lib/types";
import { StatTile } from "@/components/panels";
import { useUser } from "../user-context";

type State = "idle" | "recording" | "scoring";

function band(v: number | null) {
  if (v == null) return "text-muted bg-panel2";
  if (v >= 90) return "text-good bg-good/10";
  if (v >= 70) return "text-warn bg-warn/10";
  return "text-bad bg-bad/10";
}

export default function ReadingPage() {
  const { currentUser, currentLevel } = useUser();
  const [level, setLevel] = useState(currentLevel);
  const [passage, setPassage] = useState<ReadingPassage | null>(null);
  const [state, setState] = useState<State>("idle");
  const [status, setStatus] = useState("Tap the microphone and read it aloud");
  const [result, setResult] = useState<ReadingResult | null>(null);

  const ws = useRef<WebSocket | null>(null);
  const ac = useRef<AudioContext | null>(null);
  const proc = useRef<ScriptProcessorNode | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const startedAt = useRef(0);
  const stateRef = useRef<State>("idle");
  const passageRef = useRef<ReadingPassage | null>(null);

  // Refs shadow the state because the audio callback and the socket handler are
  // closures created once; reading React state there would see its first value
  // forever and stream audio after the learner had already stopped.
  useEffect(() => {
    stateRef.current = state;
  }, [state]);
  useEffect(() => {
    passageRef.current = passage;
  }, [passage]);

  const loadPassage = async (lvl: number) => {
    setResult(null);
    try {
      setPassage(await api.readingPassage(lvl, `${currentUser}:${Date.now()}`));
    } catch (e) {
      setStatus(`Could not load a passage: ${(e as Error).message}`);
    }
  };

  useEffect(() => {
    setLevel(currentLevel);
  }, [currentLevel]);

  useEffect(() => {
    if (currentUser) loadPassage(level);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentUser, level]);

  const teardown = () => {
    try {
      proc.current?.disconnect();
    } catch {}
    try {
      stream.current?.getTracks().forEach((t) => t.stop());
    } catch {}
    try {
      ac.current?.close();
    } catch {}
    proc.current = null;
    stream.current = null;
    ac.current = null;
  };

  const score = async (spoken: string) => {
    const seconds = (Date.now() - startedAt.current) / 1000;
    try {
      ws.current?.send(JSON.stringify({ type: "bye" }));
    } catch {}
    const p = passageRef.current;
    if (!currentUser || !p) return;
    try {
      setResult(
        await api.scoreReading(currentUser, {
          reference: p.text,
          spoken,
          duration_s: seconds,
          level: p.level,
        }),
      );
      setStatus("Tap the microphone and read it aloud");
    } catch (e) {
      setStatus(`Could not score: ${(e as Error).message}`);
    }
    setState("idle");
  };

  const start = async () => {
    if (!currentUser || !passage) return;
    try {
      ac.current = new AudioContext();
      if (ac.current.state === "suspended") await ac.current.resume();
      stream.current = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      const src = ac.current.createMediaStreamSource(stream.current);
      proc.current = ac.current.createScriptProcessor(4096, 1, 1);
      proc.current.onaudioprocess = (e) => {
        if (stateRef.current !== "recording" || ws.current?.readyState !== 1) return;
        const pcm = to16k(e.inputBuffer.getChannelData(0), ac.current!.sampleRate);
        if (pcm.byteLength) ws.current.send(pcm);
      };
      src.connect(proc.current);
      proc.current.connect(ac.current.destination);

      const u = new URL(API_BASE);
      const proto = u.protocol === "https:" ? "wss" : "ws";
      const token = getToken();
      // reply=0: the learner is reading a fixed passage, so the coach stays
      // quiet — no LLM, no TTS, no coach turn in their history.
      ws.current = new WebSocket(
        `${proto}://${u.host}/ws/session?user_id=${encodeURIComponent(currentUser)}` +
          `&mode=reading&ptt=1&reply=0${token ? `&token=${encodeURIComponent(token)}` : ""}`,
      );
      ws.current.binaryType = "arraybuffer";
      ws.current.onopen = () => {
        startedAt.current = Date.now();
        setState("recording");
        setStatus("Reading… tap again when you finish");
      };
      ws.current.onmessage = (ev) => {
        if (typeof ev.data !== "string") return;
        const m = JSON.parse(ev.data);
        if (m.type === "final") score(m.text || "");
        if (m.type === "turn_skipped") {
          setState("idle");
          setStatus("That was too short — tap and read the whole passage.");
        }
        if (m.type === "error") {
          setState("idle");
          setStatus(`Error: ${m.detail || ""}`);
        }
      };
    } catch (e) {
      setState("idle");
      setStatus(`Microphone unavailable: ${(e as Error).message}`);
      teardown();
    }
  };

  const stop = () => {
    setState("scoring");
    setStatus("Measuring your reading…");
    try {
      ws.current?.send(JSON.stringify({ type: "end" }));
    } catch {}
    teardown();
  };

  useEffect(() => () => teardown(), []);

  if (!currentUser) return <div className="text-muted">Select a learner first.</div>;

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="flex justify-between items-center gap-3 flex-wrap">
          <h2 className="font-semibold">Reading practice</h2>
          <div className="flex items-center gap-2">
            <label className="text-muted text-sm" htmlFor="lvl">
              Level
            </label>
            <select
              id="lvl"
              className="btn"
              value={level}
              onChange={(e) => setLevel(Number(e.target.value))}
            >
              {LEVEL_NAMES.map((n, i) => (
                <option key={n} value={i}>
                  {i} · {n}
                </option>
              ))}
            </select>
            <button className="btn" onClick={() => loadPassage(level)}>
              New passage
            </button>
          </div>
        </div>
        <p className="text-muted text-xs mt-2">
          Read the passage aloud. Because the text is known, accuracy and pace are measured
          exactly rather than estimated.
        </p>
      </div>

      <div className="card">
        <h3 className="font-semibold mb-2">{passage?.title ?? "Passage"}</h3>
        <p className="text-lg leading-relaxed">{passage?.text ?? "Loading…"}</p>
        <div className="flex items-center gap-4 mt-5">
          <button
            onClick={() => (state === "recording" ? stop() : start())}
            disabled={state === "scoring" || !passage}
            className={`w-14 h-14 rounded-full grid place-items-center text-xl border-none transition ${
              state === "recording"
                ? "bg-gradient-to-br from-red-500 to-red-600 text-white animate-pulse"
                : "bg-gradient-to-br from-accent to-accent2 text-white"
            } ${state === "scoring" ? "opacity-50" : ""}`}
            title="Tap to read aloud"
          >
            {state === "recording" ? "⏹" : "🎙️"}
          </button>
          <div>
            <div className="font-semibold">{status}</div>
            {passage && (
              <div className="text-muted text-xs">
                {passage.words} words · level {passage.level}
              </div>
            )}
          </div>
        </div>
      </div>

      {result && (
        <div className="card">
          <div className="flex justify-between items-center">
            <h3 className="font-semibold">Reading result</h3>
            <span className={`px-3 py-1.5 rounded-lg font-bold ${band(result.accuracy)}`}>
              {result.accuracy != null ? `${result.accuracy}%` : "—"}
            </span>
          </div>
          <p className="my-3">{result.verdict}</p>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile
              label="Accuracy"
              value={result.accuracy != null ? `${result.accuracy}%` : "—"}
              sub={`${result.matched_words}/${result.reference_words} words`}
            />
            <StatTile
              label="Pace"
              value={result.wpm != null ? String(result.wpm) : "—"}
              sub={result.pace ?? "words per minute"}
            />
            <StatTile
              label="Error rate"
              value={result.wer != null ? String(result.wer) : "—"}
              sub="per reference word"
            />
            <StatTile
              label="Time"
              value={result.duration_s != null ? `${Math.round(result.duration_s)}s` : "—"}
              sub={`${result.spoken_words} words spoken`}
            />
          </div>

          {result.missed_words.length > 0 && (
            <>
              <h4 className="font-semibold mt-5 mb-2">Missed</h4>
              <div className="flex flex-wrap gap-1.5">
                {result.missed_words.map((w, i) => (
                  <span key={`${w}${i}`} className="pill bg-bad/10 text-bad">
                    {w}
                  </span>
                ))}
              </div>
            </>
          )}

          {result.substitutions.length > 0 && (
            <>
              <h4 className="font-semibold mt-5 mb-2">Heard differently</h4>
              <div className="space-y-2">
                {result.substitutions.map((s, i) => (
                  <div
                    key={i}
                    className="rounded-lg border-l-4 border-bad bg-bad/10 px-3 py-2 text-sm"
                  >
                    <s className="text-muted">{s.expected}</s> →{" "}
                    <b className="text-good">{s.heard}</b>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
