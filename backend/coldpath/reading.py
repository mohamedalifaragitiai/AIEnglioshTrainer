"""Read-aloud exercise: a passage per level, and metrics for the attempt.

Speaking freely and reading aloud measure different things. In free speech the
reference is unknown, so scoring is a judgement; here the target text is known
exactly, which makes accuracy, omissions and insertions *countable* rather than
estimated. That is the whole point of the exercise.

The passages here are the curated floor. Serving them and nothing else turned
the exercise into a memory test — learners saw the same two texts repeatedly —
so passage_gen.py now writes a fresh one per attempt and only falls back to
this set when generation is off, failing, or the guard has paused cold work.

The reasons these exist have not gone away, and they are what the generator is
measured against: the app must work with the LLM server down, a reading score
is only comparable week to week if the difficulty is, and a generated passage
can quietly drift off-level in a way nobody notices.
"""

from __future__ import annotations

import difflib
import hashlib
import re

# Level 0..5 mirrors LEVEL_NAMES in the UIs: Beginner .. Native-like.
PASSAGES: dict[int, list[dict]] = {
    0: [
        {
            "title": "My morning",
            "text": "I wake up at seven. I drink water and eat bread. "
            "Then I walk to the shop near my house. The sun is warm today.",
        },
        {
            "title": "The blue cup",
            "text": "This is my cup. It is blue and small. I drink tea from it "
            "every day. My sister has a red one.",
        },
    ],
    1: [
        {
            "title": "A busy market",
            "text": "The market opens early on Friday. People buy fruit, bread and "
            "fish before the heat arrives. My neighbour sells oranges, and she "
            "always gives me one for free.",
        },
        {
            "title": "Learning to swim",
            "text": "When I was younger I was afraid of deep water. My cousin taught "
            "me to float first, and only then to move my arms. Now I swim every "
            "week and the fear is gone.",
        },
    ],
    2: [
        {
            "title": "Working from home",
            "text": "Working from home sounds relaxing until you try it. The hardest "
            "part is not the work itself but deciding when to stop. I keep a "
            "notebook on my desk and write down the moment I finish, otherwise "
            "the evening disappears into email.",
        },
    ],
    3: [
        {
            "title": "Why cities grow",
            "text": "Cities rarely grow because someone planned them carefully. They "
            "grow because opportunity concentrates, and people follow it. A road "
            "built for one factory becomes a street, the street becomes a "
            "district, and within a generation nobody remembers the factory.",
        },
    ],
    4: [
        {
            "title": "The limits of measurement",
            "text": "Every measurement carries an assumption about what matters. A "
            "test that counts words per minute rewards speed, and speakers adapt "
            "to whatever is counted. The difficulty is not collecting numbers but "
            "choosing ones that still mean something once people know they are "
            "being measured.",
        },
    ],
    5: [
        {
            "title": "On translation",
            "text": "A translator's hardest problem is rarely vocabulary. It is that "
            "two languages divide the world along different seams, so a sentence "
            "that is precise in one becomes either vague or oddly specific in the "
            "other. What survives the crossing is meaning; what is lost is usually "
            "the shape the meaning arrived in.",
        },
    ],
}

_WORD = re.compile(r"[a-z0-9']+")


def _words(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def passage_for(level: int, *, seed: str | None = None) -> dict:
    """A passage at ``level``, chosen deterministically from ``seed``.

    Deterministic so a refresh does not swap the text out from under a learner
    mid-attempt, but seed-varied so a learner is not handed the same passage
    every single time.
    """
    level = max(0, min(int(level), max(PASSAGES)))
    options = PASSAGES.get(level) or PASSAGES[0]
    index = 0
    if seed:
        index = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % len(options)
    chosen = options[index]
    return {
        "level": level,
        "title": chosen["title"],
        "text": chosen["text"],
        "words": len(_words(chosen["text"])),
    }


def score_reading(reference: str, spoken: str, *, duration_s: float | None) -> dict:
    """Compare a read-aloud attempt against the text it was reading.

    Accuracy is word-level and order-aware (difflib), not a bag-of-words match:
    reading the right words in the wrong order is not the same as reading the
    passage. Words-per-minute is reported from the *reference* words actually
    matched, so racing through half the text cannot inflate it.
    """
    ref, said = _words(reference), _words(spoken)
    matcher = difflib.SequenceMatcher(a=ref, b=said, autojunk=False)

    matched = sum(block.size for block in matcher.get_matching_blocks())
    missed: list[str] = []
    added: list[str] = []
    substitutions: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "delete":
            missed.extend(ref[i1:i2])
        elif tag == "insert":
            added.extend(said[j1:j2])
        elif tag == "replace":
            missed.extend(ref[i1:i2])
            added.extend(said[j1:j2])
            for a, b in zip(ref[i1:i2], said[j1:j2], strict=False):
                substitutions.append({"expected": a, "heard": b})

    accuracy = round(100.0 * matched / len(ref), 1) if ref else None
    # Errors per reference word, the standard WER shape.
    errors = len(missed) + len(added)
    wer = round(errors / len(ref), 3) if ref else None
    wpm = (
        round(matched / (duration_s / 60.0), 1)
        if duration_s and duration_s > 0 and matched
        else None
    )

    # A reading score has to answer to both halves of the task: did you say the
    # words, and did you keep a natural pace. Pace is scored as a band rather
    # than a target, since 90-160 wpm all read as fluent to a listener.
    pace = None
    if wpm is not None:
        if wpm < 60:
            pace = "slow"
        elif wpm <= 90:
            pace = "measured"
        elif wpm <= 170:
            pace = "natural"
        else:
            pace = "rushed"

    return {
        "reference_words": len(ref),
        "spoken_words": len(said),
        "matched_words": matched,
        "accuracy": accuracy,
        "wer": wer,
        "wpm": wpm,
        "pace": pace,
        "duration_s": round(duration_s, 1) if duration_s else None,
        "missed_words": missed[:40],
        "extra_words": added[:40],
        "substitutions": substitutions[:20],
        "verdict": _verdict(accuracy, pace),
    }


def _verdict(accuracy: float | None, pace: str | None) -> str:
    if accuracy is None:
        return "Nothing was transcribed — check the microphone and try again."
    if accuracy >= 95:
        base = "Excellent — nearly every word matched the passage."
    elif accuracy >= 85:
        base = "Good reading, with a few words missed or altered."
    elif accuracy >= 70:
        base = "Understandable, but several words drifted from the text."
    else:
        base = "Much of the passage did not come through — slow down and read line by line."
    tail = {
        "slow": " Pace is slow; aim for smoother phrases rather than word-by-word.",
        "measured": " Pace is steady — comfortable to follow.",
        "natural": " Pace is natural.",
        "rushed": " Pace is fast; slowing down usually raises accuracy.",
    }.get(pace or "", "")
    return base + tail
