"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { LEVEL_NAMES } from "@/lib/types";
import { useUser } from "../user-context";
import { LiveSession } from "@/components/LiveSession";
import { Icon } from "@/components/icons";

export default function Practice() {
  const { currentUser, currentLevel, modelsLoaded } = useUser();
  const [topic, setTopic] = useState("");
  const [recommended, setRecommended] = useState<string[]>([]);

  useEffect(() => {
    api
      .topics()
      .then((t) => setRecommended(t.recommended))
      .catch(() => {});
  }, []);

  if (!currentUser) return <p className="text-muted">Select a learner to practice.</p>;

  return (
    <div className="space-y-4">
      <header className="pb-1">
        <h1 className="t-display">Practice</h1>
        <p className="text-muted text-sm mt-1">
          Speak freely on any topic. Hold the mic, release to send.
        </p>
      </header>

      {!modelsLoaded && (
        <div className="rounded-xl border border-warn/40 bg-warn/10 text-warn px-4 py-3 text-sm">
          Live speaking needs the STT/LLM/TTS models running (<code>COACH_LOAD_MODELS=true</code> + a
          vLLM server). Without them the mic still streams and the server replies with an actionable
          error.
        </div>
      )}
      {/* One mode, presented as one. The reference flow shows Shadowing,
          Recording and Conversation as separate cards; those do not exist in
          this app, and a card that opens nothing is worse than no card. */}
      <div className="card !p-5">
        <div className="flex justify-between items-center gap-3 flex-wrap mb-3">
          <div className="flex items-center gap-2.5">
            <span className="icon-badge" style={{ ["--tint" as string]: "var(--sk-pronunciation)" }}>
              <Icon.mic size={17} />
            </span>
            <span>
              <span className="t-section block">Free speaking</span>
              <span className="t-caption">2-3 min · the coach replies and scores you after</span>
            </span>
          </div>
          <span className="pill bg-panel2 text-accent2">
            Level {currentLevel} · {LEVEL_NAMES[currentLevel]}
          </span>
        </div>
        <label className="t-label block mb-1.5" htmlFor="topic">
          Topic (optional)
        </label>
        <input
          id="topic"
          className="btn w-full text-left"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="What would you like to talk about? (optional)"
        />
        <div className="flex gap-2 flex-wrap mt-3">
          {recommended.map((t) => (
            <button
              key={t}
              onClick={() => setTopic(t)}
              className={`text-[12.5px] px-3 py-1.5 rounded-full border transition-colors ${
                topic === t
                  ? "bg-accent/10 border-accent text-accent"
                  : "border-line bg-panel2 text-muted hover:text-fg hover:border-accent/40"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>
      <LiveSession userId={currentUser} topic={topic} />

      <aside className="rounded-2xl border border-line surface px-4 py-3 flex items-center gap-3">
        <span className="icon-badge" style={{ ["--tint" as string]: "rgb(var(--c-accent))" }}>
          <Icon.spark size={16} />
        </span>
        <p className="text-[13px] text-muted">
          Tip: speak for the full two minutes. A longer answer gives the scoring more to
          work with than a perfect short one.
        </p>
      </aside>
    </div>
  );
}
