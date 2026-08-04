"use client";

import { useEffect, useRef, useState } from "react";
import { api, API_BASE, getToken } from "@/lib/api";
import { to16k } from "@/lib/audio";
import {
  LEVEL_NAMES,
  type ReadingHistory,
  type ReadingPassage,
  type ReadingResult,
} from "@/lib/types";
import { StatTile } from "@/components/panels";
import { useUser } from "../user-context";

// "recorded" is the new state that makes Send possible: the take is buffered on
// the server and nothing is transcribed until the learner decides to send it.
type State = "idle" | "recording" | "recorded" | "scoring";

// 150 wpm is the middle of what the scorer calls a natural pace (90-170), so the
// live guide and the grade afterwards agree rather than pulling apart.
const NATURAL_WPM = 150;

function clock(sec: number) {
  return `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, "0")}`;
}

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
  const [status, setStatus] = useState("Hold the mic and read aloud, release to send — or tap for hands-free");
  const [result, setResult] = useState<ReadingResult | null>(null);
  const [history, setHistory] = useState<ReadingHistory | null>(null);
  const [progress, setProgress] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [recSecs, setRecSecs] = useState(0);
  const [paceSecs, setPaceSecs] = useState(0);

  const ws = useRef<WebSocket | null>(null);
  const ac = useRef<AudioContext | null>(null);
  const proc = useRef<ScriptProcessorNode | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const startedAt = useRef(0);
  const stateRef = useRef<State>("idle");
  const passageRef = useRef<ReadingPassage | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  // Same gesture as Practice: hold to read, release to send. A short tap starts
  // hands-free instead, which a long passage needs — and a keyboard cannot hold.
  const TAP_MS = 350;
  const pressStart = useRef(0);
  const handsFree = useRef(false);
  const paceTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const recordedRef = useRef(0);

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

  const loadHistory = () => {
    if (!currentUser) return;
    api.readingHistory(currentUser).then(setHistory).catch(() => setHistory(null));
  };

  useEffect(() => {
    if (currentUser) loadPassage(level);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentUser, level]);

  useEffect(loadHistory, [currentUser]); // eslint-disable-line react-hooks/exhaustive-deps

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
    // The take's own length, not the time the socket has been open —
    // reviewing before sending must not count as slow reading.
    const seconds = recordedRef.current || (Date.now() - startedAt.current) / 1000;
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
          title: p.title,
        }),
      );
      setStatus("Hold the mic and read aloud, release to send — or tap for hands-free");
      if (timer.current) clearInterval(timer.current);
      timer.current = null;
      setProgress(100);
    } catch (e) {
      setStatus(`Could not score: ${(e as Error).message}`);
    }
    loadHistory();   // the attempt just became part of the trend
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
        setStatus("Reading… release to send");
        if (paceTimer.current) clearInterval(paceTimer.current);
        paceTimer.current = setInterval(
          () => setPaceSecs((Date.now() - startedAt.current) / 1000),
          200,
        );
      };
      // Without these the UI had no way to learn the socket had gone: a dropped
      // connection or a turn that never completed left "Measuring your reading…"
      // on screen indefinitely.
      ws.current.onerror = () =>
        fail("The connection dropped before your reading could be measured.");
      ws.current.onclose = (ev) => {
        if (stateRef.current !== "idle") {
          fail(
            ev.code === 4401
              ? "Your session has ended — sign in again."
              : ev.code === 4403
                ? "That profile is not yours."
                : `The connection closed before the transcript came back (code ${ev.code}).`,
          );
        }
      };
      ws.current.onmessage = (ev) => {
        if (typeof ev.data !== "string") return;
        const m = JSON.parse(ev.data);
        if (m.type === "final") score(m.text || "");
        if (m.type === "turn_skipped") {
          if (timer.current) clearInterval(timer.current);
          timer.current = null;
          setProgress(0);
          setState("idle");
          setStatus("That was too short — tap and read the whole passage.");
        }
        if (m.type === "error") fail(`Error: ${m.detail || ""}`);
      };
    } catch (e) {
      setState("idle");
      setStatus(`Microphone unavailable: ${(e as Error).message}`);
      teardown();
    }
  };

  // Transcribing a 30-second read takes real time here, and the guard can defer
  // it further. Silence for that long is indistinguishable from a hang, so show
  // elapsed seconds, ease a bar towards 90%, and give up loudly rather than
  // never.
  const READ_TIMEOUT_MS = 90_000;

  const fail = (msg: string) => {
    if (stateRef.current === "idle") return;
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    setProgress(0);
    setElapsed(0);
    setState("idle");
    setStatus(msg);
    try {
      ws.current?.close();
    } catch {}
  };

  /** Releases the microphone only. The socket stays open and the take stays
   *  buffered server-side, so the learner can discard it or send it. */
  const micDown = async (e: React.PointerEvent) => {
    e.preventDefault();
    if (stateRef.current === "scoring" || stateRef.current === "recorded") return;
    if (stateRef.current === "recording") {
      if (handsFree.current) {
        handsFree.current = false;   // second tap in hands-free: stop, offer Send
        stopRecording();
      }
      return;
    }
    pressStart.current = Date.now();
    handsFree.current = false;
    await start();
  };

  const micUp = () => {
    if (stateRef.current !== "recording" || handsFree.current) return;
    if (Date.now() - pressStart.current < TAP_MS) {
      handsFree.current = true;      // a tap: keep reading until they tap again
      setStatus("Reading… tap ⏹ when you finish");
      return;
    }
    stopRecording();
    send();                          // released after a real hold: send it
  };

  // On the window: a finger that slides off the button still has to end the take.
  useEffect(() => {
    const up = () => micUp();
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    return () => {
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stopRecording = () => {
    if (paceTimer.current) clearInterval(paceTimer.current);
    paceTimer.current = null;
    const secs = (Date.now() - startedAt.current) / 1000;
    recordedRef.current = secs;
    setRecSecs(secs);
    teardown();
    setState("recorded");
    setStatus(`Recorded ${clock(secs)} — send it for scoring, or record again`);
  };

  const discard = () => {
    // Closing without 'end' is what makes the server drop the buffered take.
    try {
      ws.current?.close();
    } catch {}
    ws.current = null;
    setState("idle");
    setStatus("Hold the mic and read aloud, release to send — or tap for hands-free");
  };

  const send = () => {
    if (stateRef.current !== "recorded") return;
    setState("scoring");
    setStatus("Measuring your reading…");
    const t0 = Date.now();
    if (timer.current) clearInterval(timer.current);
    timer.current = setInterval(() => {
      const ms = Date.now() - t0;
      setElapsed(Math.round(ms / 1000));
      // Asymptotic: quick at first, never claiming 100% while the server works.
      setProgress(Math.min(90, Math.round(90 * (1 - Math.exp(-ms / 12000)))));
      if (ms > READ_TIMEOUT_MS)
        fail(
          "Timed out waiting for the transcript. Your recording may have been too long, or the machine is under load — try again.",
        );
    }, 500);
    try {
      ws.current?.send(JSON.stringify({ type: "end" }));
    } catch {
      fail("Could not send the recording — the connection had already closed.");
    }
  };

  useEffect(
    () => () => {
      teardown();
      if (timer.current) clearInterval(timer.current);
      if (paceTimer.current) clearInterval(paceTimer.current);
    },
    [],
  );

  if (!currentUser) return <div className="text-muted">Select a learner first.</div>;

  return (
    <div className="space-y-4">
      <header className="pb-1">
        <h1 className="t-display">Reading</h1>
        <p className="text-muted text-sm mt-1">Read the passage aloud. Accuracy and pace are measured word by word.</p>
      </header>

      <div className="card !p-5">
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

      <div className="card !p-5">
        <h3 className="font-semibold mb-2">{passage?.title ?? "Passage"}</h3>
        <p className="text-lg leading-relaxed">{passage?.text ?? "Loading…"}</p>
        <div className="flex items-center gap-4 mt-5">
          <button
            onPointerDown={micDown}
            onClick={(e) => {
              // Keyboard activation only; pointer presses are handled above.
              if (e.detail !== 0) return;
              handsFree.current = true;
              if (state === "recording") stopRecording();
              else void start();
            }}
            disabled={state === "scoring" || !passage}
            className={`w-14 h-14 rounded-full grid place-items-center text-xl border-none transition ${
              state === "recording"
                ? "bg-gradient-to-br from-red-500 to-red-600 text-white animate-pulse"
                : "bg-gradient-to-br from-accent to-accent2 text-white"
            } ${state === "scoring" ? "opacity-50" : ""}`}
            title="Tap to read aloud"
            aria-label="Tap to read aloud"
          >
            {state === "recording" ? "⏹" : "🎙️"}
          </button>

          {/* Nothing is submitted until Send: stopping only releases the
              microphone, so a bad take can be discarded instead of scored. */}
          {state === "recorded" && (
            <div className="flex gap-2">
              <button className="btn btn-primary" onClick={send}>
                Send for scoring
              </button>
              <button className="btn" onClick={discard}>
                Record again
              </button>
            </div>
          )}
          <div>
            <div className="font-semibold" role="status" aria-live="polite">
              {status}
            </div>
            {passage && state !== "scoring" && (
              <div className="text-muted text-xs">
                {passage.words} words · level {passage.level}
              </div>
            )}
            {state === "recording" && passage && (
              <div className="mt-2 max-w-sm">
                <div className="h-1.5 rounded-full bg-panel2 overflow-hidden">
                  {(() => {
                    const target = Math.max(4, passage.words / (NATURAL_WPM / 60));
                    const ratio = paceSecs / target;
                    // Past the natural window this is a nudge, not a failure —
                    // some passages deserve to be read slowly.
                    const colour =
                      ratio <= 1.15
                        ? "bg-gradient-to-r from-accent to-accent2"
                        : ratio <= 1.6
                          ? "bg-warn"
                          : "bg-bad";
                    return (
                      <div
                        className={`h-full rounded-full ${colour}`}
                        style={{ width: `${Math.min(100, ratio * 100)}%` }}
                      />
                    );
                  })()}
                </div>
                <div className="flex justify-between mt-1">
                  <span className="text-muted text-xs tabular-nums">{clock(paceSecs)}</span>
                  <span className="text-muted text-[11px]">
                    natural pace ≈ {clock(passage.words / (NATURAL_WPM / 60))} for{" "}
                    {passage.words} words
                  </span>
                </div>
              </div>
            )}
            {state === "recorded" && (
              <div className="text-muted text-xs mt-1 tabular-nums">
                Recorded {clock(recSecs)} · nothing has been sent yet
              </div>
            )}
            {state === "scoring" && (
              <div className="mt-2 max-w-xs">
                <div className="h-1.5 rounded-full bg-panel2 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-accent to-accent2 transition-[width] duration-300"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <div className="text-muted text-[11px] mt-1">
                  Transcribing your recording — {elapsed}s elapsed
                  {elapsed > 25 && " (a long passage takes longer, and scoring waits its turn while the machine is busy)"}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {result && (
        <div className="card !p-5">
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

      {history && history.attempts.length > 0 && (
        <div className="card !p-5">
          <h3 className="font-semibold mb-3">Your reading over time</h3>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile
              label="Attempts"
              value={String(history.summary.attempts)}
              sub={`${history.summary.words_read} words read`}
            />
            <StatTile
              label="Best accuracy"
              value={
                history.summary.best_accuracy != null
                  ? `${history.summary.best_accuracy}%`
                  : "—"
              }
              sub={
                history.summary.avg_accuracy != null
                  ? `average ${history.summary.avg_accuracy}%`
                  : "—"
              }
            />
            <StatTile
              label="Typical pace"
              value={
                history.summary.avg_wpm != null
                  ? String(Math.round(history.summary.avg_wpm))
                  : "—"
              }
              sub="words per minute"
            />
            <StatTile
              label="Trend"
              value={
                history.summary.delta == null
                  ? "—"
                  : `${history.summary.delta > 0 ? "▲ +" : "▼ "}${history.summary.delta}`
              }
              sub={
                history.summary.delta == null
                  ? "need more attempts"
                  : "accuracy, recent vs earlier"
              }
            />
          </div>

          <div className="overflow-x-auto mt-4">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-muted">
                  <th className="text-left py-1.5 px-2 font-medium">when</th>
                  <th className="text-left py-1.5 px-2 font-medium">passage</th>
                  <th className="text-left py-1.5 px-2 font-medium">accuracy</th>
                  <th className="text-left py-1.5 px-2 font-medium">wpm</th>
                  <th className="text-left py-1.5 px-2 font-medium">pace</th>
                </tr>
              </thead>
              <tbody>
                {history.attempts.map((a) => (
                  <tr key={a.attempt_id} className="border-t border-line">
                    <td className="py-1.5 px-2 text-muted whitespace-nowrap">
                      {new Date(a.created_at).toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                      })}
                    </td>
                    <td className="py-1.5 px-2">{a.title ?? "—"}</td>
                    <td className="py-1.5 px-2">
                      <span className={`px-2 py-0.5 rounded ${band(a.accuracy)}`}>
                        {a.accuracy != null ? `${a.accuracy}%` : "—"}
                      </span>
                    </td>
                    <td className="py-1.5 px-2">{a.wpm != null ? Math.round(a.wpm) : "—"}</td>
                    <td className="py-1.5 px-2 text-muted">{a.pace ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
