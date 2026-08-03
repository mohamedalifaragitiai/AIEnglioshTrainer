"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { LEVEL_NAMES } from "@/lib/types";
import { useUser } from "../user-context";
import { LiveSession } from "@/components/LiveSession";

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
      {!modelsLoaded && (
        <div className="rounded-lg border border-warn/40 bg-warn/10 text-warn px-4 py-2.5 text-sm">
          Live speaking needs the STT/LLM/TTS models running (<code>COACH_LOAD_MODELS=true</code> + a
          vLLM server). Without them the mic still streams and the server replies with an actionable
          error.
        </div>
      )}
      <div className="card">
        <div className="flex justify-between items-center">
          <div className="card-title mb-0">Topic</div>
          <span className="pill bg-panel2 text-accent2">
            Level {currentLevel} · {LEVEL_NAMES[currentLevel]}
          </span>
        </div>
        <input
          className="btn w-full mt-2"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="What would you like to talk about? (optional)"
        />
        <div className="flex gap-2 flex-wrap mt-2.5">
          {recommended.map((t) => (
            <button
              key={t}
              onClick={() => setTopic(t)}
              className={`text-[12.5px] px-3 py-1.5 rounded-full border ${
                topic === t ? "bg-accent/10 border-accent text-accent" : "border-line bg-panel2"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>
      <LiveSession userId={currentUser} topic={topic} />
    </div>
  );
}
