"use client";

import { useRef, useState } from "react";
import { api } from "@/lib/api";

type Msg = { who: "user" | "coach"; text: string };
const TTS_RATE = 24000; // Kokoro output rate (used when models are on)

export function LiveSession({ userId }: { userId: string }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [status, setStatus] = useState("disconnected");
  const [recording, setRecording] = useState(false);
  const [timings, setTimings] = useState("");

  const ws = useRef<WebSocket | null>(null);
  const ac = useRef<AudioContext | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const proc = useRef<ScriptProcessorNode | null>(null);
  const playHead = useRef(0);
  const coachOpen = useRef(false); // are we mid-stream on a coach reply?

  const add = (m: Msg) => setMessages((prev) => [...prev, m]);

  const appendCoach = (piece: string) => {
    const cont = coachOpen.current;
    coachOpen.current = true;
    setMessages((prev) => {
      if (cont && prev.length && prev[prev.length - 1].who === "coach") {
        const last = prev[prev.length - 1];
        const merged = { ...last, text: (last.text ? last.text + " " : "") + piece };
        return [...prev.slice(0, -1), merged];
      }
      return [...prev, { who: "coach", text: piece }];
    });
  };

  function floatTo16kPCM(input: Float32Array, inRate: number): ArrayBuffer {
    const ratio = inRate / 16000;
    const outLen = Math.floor(input.length / ratio);
    const out = new Int16Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const s = Math.max(-1, Math.min(1, input[Math.floor(i * ratio)]));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return out.buffer;
  }

  function playPCM(int16: Int16Array) {
    const ctx = ac.current;
    if (!ctx) return;
    const buf = ctx.createBuffer(1, int16.length, TTS_RATE);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < int16.length; i++) ch[i] = int16[i] / 32768;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    const now = ctx.currentTime;
    if (playHead.current < now) playHead.current = now;
    src.start(playHead.current);
    playHead.current += buf.duration;
  }

  async function start() {
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
    } catch {
      alert("Microphone access denied.");
      return;
    }
    ac.current = new AudioContext();
    playHead.current = ac.current.currentTime;
    const socket = new WebSocket(api.wsUrl(userId));
    socket.binaryType = "arraybuffer";
    ws.current = socket;
    setStatus("connecting…");

    socket.onopen = () => setStatus("connected — speak, then pause");
    socket.onclose = () => setStatus("disconnected");
    socket.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        const m = JSON.parse(ev.data);
        if (m.type === "final") {
          coachOpen.current = false;
          add({ who: "user", text: m.text || "(…)" });
        } else if (m.type === "reply") {
          appendCoach(m.text || "");
        } else if (m.type === "turn_end") {
          coachOpen.current = false;
          setTimings(
            `first audio ${m.timings.first_audio_ms}ms · stt ${m.timings.stt_ms} · llm ${m.timings.llm_ms}`,
          );
        } else if (m.type === "error") {
          coachOpen.current = false;
          add({ who: "coach", text: "⚠ " + (m.detail || "error") });
        }
      } else {
        playPCM(new Int16Array(ev.data as ArrayBuffer));
      }
    };

    const source = ac.current.createMediaStreamSource(stream.current);
    const node = ac.current.createScriptProcessor(4096, 1, 1);
    proc.current = node;
    node.onaudioprocess = (e) => {
      if (!ws.current || ws.current.readyState !== 1) return;
      const pcm = floatTo16kPCM(e.inputBuffer.getChannelData(0), ac.current!.sampleRate);
      if (pcm.byteLength) ws.current.send(pcm);
    };
    source.connect(node);
    node.connect(ac.current.destination);
    setRecording(true);
  }

  function stop() {
    setRecording(false);
    try {
      if (ws.current?.readyState === 1) {
        ws.current.send(JSON.stringify({ type: "end" }));
        ws.current.send(JSON.stringify({ type: "bye" }));
      }
    } catch {}
    proc.current?.disconnect();
    proc.current = null;
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    setTimeout(() => ws.current?.close(), 400);
  }

  return (
    <div className="card">
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <button className={recording ? "btn" : "btn btn-primary"} onClick={recording ? stop : start}>
          {recording ? "⏹ Stop" : "🎙 Start speaking"}
        </button>
        <span
          className={`w-2.5 h-2.5 rounded-full ${recording ? "bg-red-400 animate-pulse" : "bg-muted"}`}
        />
        <span className="text-muted text-sm">{status}</span>
        <div className="flex-1" />
        <span className="text-muted text-sm">{timings}</span>
      </div>
      <div className="flex flex-col gap-2.5 min-h-[220px] max-h-[46vh] overflow-y-auto">
        {messages.map((m, i) => (
          <div
            key={i}
            className={`px-3 py-2 rounded-xl max-w-[78%] whitespace-pre-wrap ${
              m.who === "user"
                ? "self-end bg-blue-900/30 border border-blue-600/40"
                : "self-start bg-panel2 border border-line"
            }`}
          >
            <div className="text-xs text-muted mb-0.5">{m.who === "user" ? "You" : "Coach"}</div>
            {m.text}
          </div>
        ))}
      </div>
    </div>
  );
}
