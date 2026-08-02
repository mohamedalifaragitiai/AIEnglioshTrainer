"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, setToken } from "@/lib/api";
import { LEVEL_NAMES } from "@/lib/types";
import { useUser } from "../user-context";

type Note = { text: string; bad: boolean } | null;

export default function SettingsPage() {
  const { users, currentUser, currentLevel, refresh, minPasswordLength, signedInAs } =
    useUser();
  const router = useRouter();

  const [name, setName] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [country, setCountry] = useState("");
  const [nativeLanguage, setNativeLanguage] = useState("");
  const [goal, setGoal] = useState("");
  const [voice, setVoice] = useState<"female" | "male">("female");
  const [level, setLevel] = useState(currentLevel);
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [note, setNote] = useState<Note>(null);
  const [busy, setBusy] = useState(false);

  const user = users.find((u) => u.user_id === currentUser);

  useEffect(() => {
    if (user) {
      setName(user.display_name);
      setFullName(user.full_name ?? "");
      setEmail(user.email ?? "");
      setCountry(user.country ?? "");
      setNativeLanguage(user.native_language ?? "");
      setGoal(user.goal ?? "");
      setVoice(user.voice ?? "female");
      setLevel(user.current_level);
    }
  }, [user]);

  if (!currentUser) return <div className="text-muted">Select a learner first.</div>;

  const saveProfile = async () => {
    if (!name.trim()) return setNote({ text: "A display name cannot be empty.", bad: true });
    setBusy(true);
    try {
      // Only send what is filled in: the endpoint writes the fields it
      // receives, so empty strings would blank details this form did not ask
      // about.
      const patch: Record<string, string> = { display_name: name.trim(), voice };
      const optional: [string, string][] = [
        ["full_name", fullName],
        ["email", email],
        ["country", country],
        ["native_language", nativeLanguage],
        ["goal", goal],
      ];
      for (const [key, value] of optional) {
        if (value.trim()) patch[key] = value.trim();
      }
      await api.updateProfile(currentUser, patch);
      // POST /level, not PATCH: choosing a level is a decision, and PATCH is
      // what the scoring pipeline uses when it moves someone automatically.
      await api.chooseLevel(currentUser, level);
      await refresh();
      setNote({ text: "Profile saved. A new voice applies to your next reply.", bad: false });
    } catch (e) {
      setNote({ text: `Could not save: ${(e as Error).message}`, bad: true });
    }
    setBusy(false);
  };

  const changePassword = async () => {
    if (!currentPw || !newPw)
      return setNote({ text: "Both the current and the new password are required.", bad: true });
    setBusy(true);
    try {
      const session = await api.changePassword(currentPw, newPw);
      // The change revokes every other session and hands back a fresh token for
      // this one; storing it is what keeps this tab signed in.
      if (session?.token) setToken(session.token);
      setCurrentPw("");
      setNewPw("");
      setNote({ text: "Password changed. Other devices have been signed out.", bad: false });
    } catch (e) {
      const raw = (e as Error).message;
      const detail = (() => {
        const brace = raw.indexOf("{");
        if (brace < 0) return raw;
        try {
          return JSON.parse(raw.slice(brace)).detail ?? raw;
        } catch {
          return raw;
        }
      })();
      setNote({ text: String(detail), bad: true });
    }
    setBusy(false);
  };

  const logoutEverywhere = async () => {
    if (!confirm("Sign out on every device, including this one?")) return;
    await api.logoutAll().catch(() => {});
    setToken(null);
    router.push("/login");
  };

  const deleteAccount = async () => {
    // Typing the id rather than clicking twice: this is unrecoverable, and a
    // confirm dialog is something people dismiss without reading.
    const typed = prompt(
      `This deletes your profile and everything in it, permanently.\n\nType your learner id (${currentUser}) to confirm:`,
    );
    if (typed === null) return;
    if (typed.trim() !== currentUser) {
      return setNote({
        text: "That did not match your learner id — nothing was deleted.",
        bad: true,
      });
    }
    try {
      await api.deleteUser(currentUser);
      setToken(null);
      router.push("/login");
    } catch (e) {
      setNote({ text: `Could not delete the account: ${(e as Error).message}`, bad: true });
    }
  };

  return (
    <div className="max-w-xl space-y-4">
      <h1 className="text-xl font-semibold">Account settings</h1>

      {note && (
        <div
          className={`rounded-lg px-4 py-2.5 text-sm border-l-4 ${
            note.bad ? "border-bad bg-bad/10 text-bad" : "border-good bg-good/10 text-good"
          }`}
        >
          {note.text}
        </div>
      )}

      <div className="card space-y-3">
        <h2 className="font-semibold">Profile</h2>
        <label className="text-muted text-xs block" htmlFor="name">
          Display name
        </label>
        <input
          id="name"
          className="btn text-left w-full"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <label className="text-muted text-xs block" htmlFor="full_name">
          Full name
        </label>
        <input
          id="full_name"
          className="btn text-left w-full"
          placeholder="Your full name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
        />
        <label className="text-muted text-xs block" htmlFor="email">
          Email
        </label>
        <input
          id="email"
          className="btn text-left w-full"
          placeholder="you@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <label className="text-muted text-xs block" htmlFor="country">
          Country
        </label>
        <input
          id="country"
          className="btn text-left w-full"
          placeholder="Egypt"
          value={country}
          onChange={(e) => setCountry(e.target.value)}
        />
        <label className="text-muted text-xs block" htmlFor="native">
          Native language
        </label>
        <input
          id="native"
          className="btn text-left w-full"
          placeholder="Arabic"
          value={nativeLanguage}
          onChange={(e) => setNativeLanguage(e.target.value)}
        />
        <label className="text-muted text-xs block" htmlFor="goal">
          Why are you learning?
        </label>
        <input
          id="goal"
          className="btn text-left w-full"
          placeholder="Work, travel, exams…"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
        />
        <label className="text-muted text-xs block" htmlFor="voice">
          Coach voice
        </label>
        <select
          id="voice"
          className="btn w-full"
          value={voice}
          onChange={(e) => setVoice(e.target.value as "female" | "male")}
        >
          <option value="female">Woman</option>
          <option value="male">Man</option>
        </select>
        <label className="text-muted text-xs block" htmlFor="level">
          Level
        </label>
        <select
          id="level"
          className="btn w-full"
          value={level}
          onChange={(e) => setLevel(Number(e.target.value))}
        >
          {LEVEL_NAMES.map((n, i) => (
            <option key={n} value={i}>
              {i} · {n}
            </option>
          ))}
        </select>
        {/* Sticky: the panel scrolls, and a Save you have to hunt for is one
            people miss — after which the setting looks broken, not unsaved. */}
        <div className="sticky bottom-0 -mx-4 mt-2 px-4 pt-3 pb-1 bg-panel border-t border-line">
          <button
            className="btn btn-primary w-full"
            disabled={busy}
            onClick={saveProfile}
          >
            Save changes
          </button>
          <p className="text-muted text-[11px] text-center mt-1.5">
            Saves your profile, level and coach voice.
          </p>
        </div>
      </div>

      {signedInAs && (
        <>
          <div className="card space-y-3">
            <h2 className="font-semibold">Password</h2>
            <input
              className="btn text-left w-full"
              type="password"
              placeholder="Current password"
              autoComplete="current-password"
              value={currentPw}
              onChange={(e) => setCurrentPw(e.target.value)}
            />
            <input
              className="btn text-left w-full"
              type="password"
              placeholder="New password"
              autoComplete="new-password"
              minLength={minPasswordLength}
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
            />
            {minPasswordLength > 1 && (
              <p className="text-muted text-xs">At least {minPasswordLength} characters.</p>
            )}
            <button className="btn btn-primary" disabled={busy} onClick={changePassword}>
              Change password
            </button>
          </div>

          <div className="card space-y-2">
            <h2 className="font-semibold">Sessions</h2>
            <p className="text-muted text-sm">
              Signs you out on every device, including this one.
            </p>
            <button className="btn" onClick={logoutEverywhere}>
              Sign out everywhere
            </button>
          </div>
        </>
      )}

      <div className="card space-y-2">
        <h2 className="font-semibold text-bad">Delete account</h2>
        <p className="text-muted text-sm">
          Permanently removes your profile and every conversation, score and reading attempt.
          This cannot be undone.
        </p>
        <button className="btn border-bad text-bad" onClick={deleteAccount}>
          Delete my account
        </button>
      </div>
    </div>
  );
}
