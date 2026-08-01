"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

type Msg = { who: "user" | "coach"; text: string };
type St = "idle" | "recording" | "busy";
const TTS_RATE = 24000;

export function LiveSession({ userId, topic }: { userId: string; topic: string }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [state, _setState] = useState<St>("idle");
  const [status, setStatus] = useState("Tap the mic to speak");
  const [timings, setTimings] = useState("");
  const [recMs, setRecMs] = useState(0);

  const stateRef = useRef<St>("idle");
  const ws = useRef<WebSocket | null>(null);
  const ac = useRef<AudioContext | null>(null);
  const micStream = useRef<MediaStream | null>(null);
  const source = useRef<MediaStreamAudioSourceNode | null>(null);
  const proc = useRef<ScriptProcessorNode | null>(null);
  const playHead = useRef(0);
  const coachOpen = useRef(false);
  const recStart = useRef(0);
  const recTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const setSt = (s: St) => {
    stateRef.current = s;
    _setState(s);
    if (recTimer.current) {
      clearInterval(recTimer.current);
      recTimer.current = null;
    }
    if (s === "recording") {
      recStart.current = Date.now();
      setRecMs(0);
      recTimer.current = setInterval(() => setRecMs(Date.now() - recStart.current), 250);
    }
    setStatus(
      s === "recording" ? "recording" : s === "busy" ? "Coach is responding" : "Tap the mic to speak",
    );
  };

  useEffect(
    () => () => {
      try {
        ws.current?.close();
      } catch {
        /* noop */
      }
      if (recTimer.current) clearInterval(recTimer.current);
      micStream.current?.getTracks().forEach((t) => t.stop());
    },
    [],
  );

  const appendCoach = (piece: string) => {
    const cont = coachOpen.current;
    coachOpen.current = true;
    setMessages((p) => {
      if (cont && p.length && p[p.length - 1].who === "coach") {
        const last = p[p.length - 1];
        return [...p.slice(0, -1), { ...last, text: (last.text ? last.text + " " : "") + piece }];
      }
      return [...p, { who: "coach", text: piece }];
    });
  };

  function to16k(input: Float32Array, rate: number): ArrayBuffer {
    const ratio = rate / 16000;
    const n = Math.floor(input.length / ratio);
    const out = new Int16Array(n);
    for (let i = 0; i < n; i++) {
      const s = Math.max(-1, Math.min(1, input[Math.floor(i * ratio)]));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return out.buffer;
  }
  function playPCM(i16: Int16Array) {
    const a = ac.current;
    if (!a) return;
    const buf = a.createBuffer(1, i16.length, TTS_RATE);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < i16.length; i++) ch[i] = i16[i] / 32768;
    const s = a.createBufferSource();
    s.buffer = buf;
    s.connect(a.destination);
    const now = a.currentTime;
    if (playHead.current < now) playHead.current = now;
    s.start(playHead.current);
    playHead.current += buf.duration;
  }

  function ctrl(m: { type: string; text?: string; detail?: string; timings?: Record<string, number> }) {
    if (m.type === "final") {
      coachOpen.current = false;
      setMessages((p) => [...p, { who: "user", text: m.text || "…" }]);
    } else if (m.type === "reply") {
      appendCoach(m.text || "");
    } else if (m.type === "turn_end" && m.timings) {
      const t = m.timings;
      setTimings(
        `first audio ${Math.round(t.first_audio_ms)}ms · stt ${Math.round(t.stt_ms)} · llm ${Math.round(t.llm_ms)} · tts ${Math.round(t.tts_first_ms)}`,
      );
      coachOpen.current = false;
      setSt("idle");
    } else if (m.type === "turn_skipped") {
      // The take was too short to score. Release the mic — nothing was said.
      setTimings(m.detail || "too short");
      coachOpen.current = false;
      setSt("idle");
    } else if (m.type === "error") {
      setMessages((p) => [...p, { who: "coach", text: "⚠ " + (m.detail || "error") }]);
      coachOpen.current = false;
      setSt("idle");
    }
  }

  async function ensureSession(): Promise<boolean> {
    if (ws.current && ws.current.readyState === 1) return true;
    try {
      if (!micStream.current)
        micStream.current = await navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
    } catch {
      alert("Microphone access denied.");
      return false;
    }
    if (!ac.current) ac.current = new AudioContext();
    if (ac.current.state === "suspended") await ac.current.resume();
    playHead.current = ac.current.currentTime;
    source.current = ac.current.createMediaStreamSource(micStream.current);
    proc.current = ac.current.createScriptProcessor(4096, 1, 1);
    proc.current.onaudioprocess = (e) => {
      if (stateRef.current !== "recording" || !ws.current || ws.current.readyState !== 1) return;
      const pcm = to16k(e.inputBuffer.getChannelData(0), ac.current!.sampleRate);
      if (pcm.byteLength) ws.current.send(pcm);
    };
    proc.current.connect(ac.current.destination); // silent (we never write output) → no echo
    const socket = new WebSocket(api.wsUrl(userId, topic || undefined));
    socket.binaryType = "arraybuffer";
    ws.current = socket;
    await new Promise<void>((res) => {
      socket.onopen = () => res();
      socket.onerror = () => res();
    });
    socket.onclose = () => setSt("idle");
    socket.onmessage = (ev) => {
      if (typeof ev.data === "string") ctrl(JSON.parse(ev.data));
      else playPCM(new Int16Array(ev.data as ArrayBuffer));
    };
    return socket.readyState === 1;
  }

  async function onMic() {
    if (state === "busy") return;
    if (state === "recording") {
      try {
        source.current?.disconnect(proc.current!); // stop mic BEFORE coach speaks (no overlap)
      } catch {
        /* noop */
      }
      try {
        ws.current?.send(JSON.stringify({ type: "end" }));
      } catch {
        /* noop */
      }
      setSt("busy");
      return;
    }
    if (!(await ensureSession())) return;
    try {
      source.current?.connect(proc.current!);
    } catch {
      /* noop */
    }
    setSt("recording");
  }
  function endSession() {
    try {
      ws.current?.send(JSON.stringify({ type: "bye" }));
    } catch {
      /* noop */
    }
    micStream.current?.getTracks().forEach((t) => t.stop());
    micStream.current = null;
    setTimeout(() => {
      ws.current?.close();
      ws.current = null;
      setSt("idle");
    }, 400);
  }

  const fmt = (ms: number) => {
    const s = Math.floor(ms / 1000);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  };
  const connected = ws.current && ws.current.readyState === 1;

  return (
    <div className="card p-0 flex flex-col overflow-hidden">
      <div className="flex-1 p-[18px] min-h-[280px] max-h-[56vh] overflow-y-auto flex flex-col gap-2.5">
        {messages.length === 0 && (
          <div className="m-auto text-center text-[var(--muted)] text-sm">
            Tap the microphone and start the conversation 🎙
          </div>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`px-3.5 py-2.5 rounded-2xl max-w-[80%] whitespace-pre-wrap ${
              m.who === "user"
                ? "self-end bg-blue-900/30 border border-blue-600/40"
                : "self-start bg-panel2 border border-line"
            }`}
          >
            <div className="text-[11px] text-muted mb-0.5 font-semibold">
              {m.who === "user" ? "You" : "Coach"}
            </div>
            {m.text}
          </div>
        ))}
      </div>
      <div className="flex items-center gap-3.5 px-[18px] py-3.5 border-t border-line bg-[linear-gradient(180deg,transparent,rgba(45,212,191,0.04))]">
        <div className="flex-1 min-w-0">
          <div className="font-semibold">
            {state === "recording" ? (
              <span className="text-red-400 font-bold">● Recording {fmt(recMs)} — tap to send</span>
            ) : state === "busy" ? (
              <span>
                Coach is responding
                <span className="inline-flex gap-1 ml-1.5 align-middle">
                  <i className="w-1.5 h-1.5 rounded-full bg-accent animate-bounce" />
                  <i className="w-1.5 h-1.5 rounded-full bg-accent animate-bounce [animation-delay:150ms]" />
                  <i className="w-1.5 h-1.5 rounded-full bg-accent animate-bounce [animation-delay:300ms]" />
                </span>
              </span>
            ) : (
              status
            )}
          </div>
          {timings && <div className="text-muted text-[11.5px]">{timings}</div>}
        </div>
        {connected && (
          <button className="btn border-red-500 text-red-400" onClick={endSession}>
            End
          </button>
        )}
        <button
          onClick={onMic}
          disabled={state === "busy"}
          className={`w-14 h-14 rounded-full grid place-items-center text-xl border-none transition ${
            state === "recording"
              ? "bg-gradient-to-br from-red-500 to-red-600 text-white animate-pulse"
              : "bg-gradient-to-br from-accent to-teal-600 text-[#052a25]"
          } ${state === "busy" ? "opacity-50" : ""}`}
          title="Tap to speak"
        >
          {/* U+FE0F on the mic: without it many platforms render the
              monochrome text glyph instead of the colour emoji. */}
          {state === "recording" ? "⏹" : state === "busy" ? "●" : "🎙️"}
        </button>
      </div>
    </div>
  );
}
