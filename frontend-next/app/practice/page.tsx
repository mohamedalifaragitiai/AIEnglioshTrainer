"use client";

import { useUser } from "../user-context";
import { LiveSession } from "@/components/LiveSession";

export default function Practice() {
  const { currentUser, modelsLoaded } = useUser();
  if (!currentUser) return <p className="text-muted">Select a learner to practice.</p>;
  return (
    <div className="space-y-4">
      {!modelsLoaded && (
        <div className="rounded-lg border border-yellow-700 bg-yellow-950/40 text-yellow-300 px-4 py-2.5 text-sm">
          Live speaking needs the STT/LLM/TTS models running (<code>COACH_LOAD_MODELS=true</code> + a
          vLLM server). Without them the mic still streams and the server replies with an actionable
          error — the plumbing works; only the models are off.
        </div>
      )}
      <LiveSession userId={currentUser} />
    </div>
  );
}
