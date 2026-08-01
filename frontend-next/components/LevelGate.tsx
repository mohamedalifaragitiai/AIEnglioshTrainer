"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { LEVEL_NAMES } from "@/lib/types";
import { useUser } from "@/app/user-context";

// "Level 3" means nothing to someone who has never taken a placement test, so
// each option says what it feels like to be at that level.
const BLURBS = [
  "I know a few words and simple phrases",
  "I can handle everyday conversations slowly",
  "I can discuss familiar topics comfortably",
  "I can work and present in English",
  "I can argue nuance and follow fast speech",
  "I speak with near-native ease",
];

/**
 * Asked once, on the learner's own profile, when the server says they have not
 * chosen. current_level alone cannot answer this — 0 is both "Beginner" and
 * "never asked" — which is why the API carries a separate level_selected flag.
 */
export function LevelGate() {
  const { users, currentUser, refresh } = useUser();
  const router = useRouter();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const user = users.find((u) => u.user_id === currentUser);
  if (!user || user.level_selected) return null;

  const choose = async (level: number) => {
    setSaving(true);
    setError(null);
    try {
      await api.chooseLevel(user.user_id, level);
      await refresh();
      // Straight to the thing that produces data. A brand-new learner
      // landing on a dashboard of zeros has nothing to do there.
      router.push("/practice");
    } catch (e) {
      setError((e as Error).message);
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 backdrop-blur-sm p-5">
      <div className="card max-w-lg w-full">
        <h2 className="text-lg font-semibold mb-1">What is your English level?</h2>
        <p className="text-muted text-sm mb-4">
          Pick where you are today. It only sets your starting point — your level moves with
          your scores from here.
        </p>
        <div className="flex flex-col gap-2">
          {LEVEL_NAMES.map((name, i) => (
            <button
              key={name}
              disabled={saving}
              onClick={() => choose(i)}
              className="btn text-left disabled:opacity-50"
            >
              <span className="font-semibold">
                {i} · {name}
              </span>
              <span className="block text-muted text-xs">{BLURBS[i]}</span>
            </button>
          ))}
        </div>
        {error && <p className="text-bad text-sm mt-3">{error}</p>}
      </div>
    </div>
  );
}
