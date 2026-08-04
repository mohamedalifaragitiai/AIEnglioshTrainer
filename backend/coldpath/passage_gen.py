"""Generate a fresh read-aloud passage at a requested level.

Learners were being handed the same two or three curated texts over and over,
which stops measuring reading and starts measuring memory. This writes a new
passage with the local LLM instead.

The reason passages were curated in the first place still stands, though: a
generated text can quietly drift off-level, and a reading score is only
comparable week to week if the difficulty is. So nothing reaches a learner
unchecked — every candidate is measured (length, sentence length, syllable
load, Flesch reading ease) against a band for its level, and a passage outside
the band is rejected and regenerated. If generation fails, is switched off, or
the box is under load, the curated set is the floor: the exercise never breaks
because a model was busy.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass

from backend.coldpath.reading import passage_for as curated
from backend.core.logging import get_logger

log = get_logger("passage_gen")

SYSTEM_PROMPT = (
    "You write short reading passages for English learners. You follow the "
    "requested difficulty and length exactly, and you reply with JSON only."
)
# Enough for the longest passage (160 words) plus the JSON wrapper and a title.
MAX_TOKENS = 512
# Qwen emits a reasoning block unless told not to; belt and braces, since a
# stray one would be parsed as the passage.
_NO_THINKING = {"chat_template_kwargs": {"enable_thinking": False}}
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)

_WORD = re.compile(r"[a-zA-Z']+")
_SENTENCE = re.compile(r"[.!?]+")
_VOWEL_RUN = re.compile(r"[aeiouy]+")


@dataclass(frozen=True)
class LevelSpec:
    """What a passage at this level has to look like to be usable.

    The bands are deliberately wide. They are a guard against a passage landing
    at the wrong level, not a target to hit exactly — a narrow band would reject
    most of what the model writes and spend the whole budget retrying.
    """

    words: tuple[int, int]
    max_avg_sentence: float
    hard_word_ratio: tuple[float, float]  # share of words with 3+ syllables
    ease: tuple[float, float]  # Flesch reading ease, inclusive
    guidance: str


# Level 0..5 mirrors LEVEL_NAMES in both UIs: Beginner .. Native-like.
SPECS: dict[int, LevelSpec] = {
    0: LevelSpec(
        words=(20, 55),
        max_avg_sentence=9.0,
        hard_word_ratio=(0.00, 0.06),
        ease=(78.0, 120.0),
        guidance=(
            "Use only the most common English words. Short simple sentences of "
            "5-8 words. Present tense. Everyday subjects: food, home, family, "
            "weather. No idioms, no clauses joined by 'which' or 'although'."
        ),
    ),
    1: LevelSpec(
        words=(25, 75),
        max_avg_sentence=13.0,
        hard_word_ratio=(0.00, 0.10),
        ease=(65.0, 105.0),
        guidance=(
            "Common everyday vocabulary. Sentences of 8-12 words, mostly simple, "
            "a few joined with 'and', 'but' or 'because'. Past and present tense. "
            "Concrete situations a learner meets daily."
        ),
    ),
    2: LevelSpec(
        words=(40, 100),
        max_avg_sentence=17.0,
        hard_word_ratio=(0.06, 0.18),
        ease=(55.0, 90.0),
        guidance=(
            "Ordinary vocabulary with a few less common words. Sentences of "
            "12-16 words, some with a relative clause. Mix of tenses. A short "
            "opinion or a small story with a point."
        ),
    ),
    3: LevelSpec(
        words=(35, 120),
        max_avg_sentence=21.0,
        hard_word_ratio=(0.12, 0.30),
        ease=(28.0, 78.0),
        guidance=(
            "Varied vocabulary including abstract nouns. Sentences of 15-20 "
            "words with subordinate clauses. An argument or an explanation that "
            "develops across sentences."
        ),
    ),
    4: LevelSpec(
        words=(40, 140),
        max_avg_sentence=25.0,
        hard_word_ratio=(0.15, 0.34),
        ease=(25.0, 65.0),
        guidance=(
            "Precise, less frequent vocabulary. Longer sentences with embedded "
            "clauses and some hedging. A nuanced point on society, science or "
            "work, developed rather than merely stated."
        ),
    ),
    5: LevelSpec(
        words=(45, 160),
        max_avg_sentence=30.0,
        hard_word_ratio=(0.18, 0.45),
        ease=(10.0, 55.0),
        guidance=(
            "Sophisticated register: subordination, qualification, a controlled "
            "figure of speech. Vocabulary an educated native reader knows. Deny "
            "the reader an easy summary — the passage should reward attention."
        ),
    ),
}

# Rotated through so consecutive passages are not all about the same thing. The
# model gets one as a nudge; it is not a template.
TOPICS = (
    "a small daily habit",
    "a journey or a commute",
    "food and cooking",
    "weather and the seasons",
    "learning something difficult",
    "work and study",
    "a city and its people",
    "technology in ordinary life",
    "friendship or family",
    "money and choices",
    "health and rest",
    "a memory from childhood",
    "nature and animals",
    "music or reading",
    "a mistake and what it taught",
    "the sea, mountains or travel",
)


def count_syllables(word: str) -> int:
    """Vowel-group count, the standard cheap approximation.

    Not linguistically exact and does not need to be: it feeds a ratio compared
    against a wide band, where being wrong on the odd word changes nothing.
    """
    w = word.lower().strip("'")
    if not w:
        return 0
    groups = len(_VOWEL_RUN.findall(w))
    # Silent terminal 'e' ("cake" is one syllable, not two) — but never zero.
    if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and groups > 1:
        groups -= 1
    return max(1, groups)


def readability(text: str) -> dict:
    """Length, sentence length, syllable load and Flesch reading ease."""
    words = _WORD.findall(text)
    sentences = [s for s in _SENTENCE.split(text) if s.strip()]
    n_words, n_sent = len(words), max(1, len(sentences))
    syllables = [count_syllables(w) for w in words]
    total_syl = sum(syllables) or 1
    hard = sum(1 for s in syllables if s >= 3)
    avg_sentence = n_words / n_sent
    avg_syl = total_syl / max(1, n_words)
    ease = 206.835 - 1.015 * avg_sentence - 84.6 * avg_syl
    return {
        "words": n_words,
        "sentences": n_sent,
        "avg_sentence": round(avg_sentence, 2),
        "hard_word_ratio": round(hard / max(1, n_words), 3),
        "ease": round(ease, 1),
    }


def check(text: str, level: int) -> tuple[bool, str]:
    """Is this passage usable at ``level``? Returns (ok, reason-if-not)."""
    spec = SPECS[max(0, min(int(level), max(SPECS)))]
    m = readability(text)
    lo, hi = spec.words
    if not lo <= m["words"] <= hi:
        return False, f"length {m['words']} outside {lo}-{hi}"
    if m["avg_sentence"] > spec.max_avg_sentence:
        return False, f"sentences average {m['avg_sentence']} > {spec.max_avg_sentence}"
    hard_lo, hard_hi = spec.hard_word_ratio
    # A floor as well as a ceiling: without it a plain, easy text passes at
    # level 5 simply by being short-sentenced, and "level 5" stops meaning
    # anything. The ceiling stops the opposite.
    if not hard_lo <= m["hard_word_ratio"] <= hard_hi:
        return False, f"hard words {m['hard_word_ratio']} outside {hard_lo}-{hard_hi}"
    ease_lo, ease_hi = spec.ease
    if not ease_lo <= m["ease"] <= ease_hi:
        return False, f"reading ease {m['ease']} outside {ease_lo}-{ease_hi}"
    return True, ""


def build_prompt(level: int, topic: str) -> str:
    spec = SPECS[max(0, min(int(level), max(SPECS)))]
    lo, hi = spec.words
    # State the thing that is actually measured. "Sophisticated register" is
    # advice a small model agrees with and then ignores; "one word in six must
    # have three or more syllables" is the check it has to pass, and asking for
    # it directly is what stopped level 4 and 5 coming back too easy.
    hard_lo = spec.hard_word_ratio[0]
    if hard_lo > 0:
        density = (
            f"Vocabulary weight: at least one word in {max(2, round(1 / hard_lo))} must "
            "have three or more syllables. Reach for the precise, formal word rather "
            "than the plain one.\n"
        )
    else:
        density = (
            "Vocabulary weight: almost every word should be one or two syllables. "
            "Avoid long words entirely.\n"
        )
    return (
        f"Write a passage to be read aloud by an English learner at level "
        f"{level} of 5 (0 = beginner, 5 = native-like).\n\n"
        f"Difficulty: {spec.guidance}\n"
        f"{density}"
        f"Length: between {lo} and {hi} words.\n"
        f"Subject: {topic}.\n\n"
        "Rules:\n"
        "- Plain prose only. No lists, no headings, no markdown, no quotation marks "
        "around the whole passage.\n"
        "- Only characters an English keyboard has: no em dashes, no curly quotes, "
        "no emoji.\n"
        "- It must read naturally aloud. Avoid numbers written as digits, "
        "abbreviations and anything whose pronunciation is ambiguous.\n"
        "- Do not mention this instruction, the level, or that it is an exercise.\n\n"
        'Reply with JSON and nothing else: {"title": "...", "text": "..."} '
        "where title is at most four words."
    )


# Straight ASCII for anything the model insists on typing typographically: the
# learner reads this aloud and the transcript is matched word by word, so a
# curly apostrophe becomes a mismatch nobody can see.
_PUNCT = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...", " ": " ",
}


def clean(text: str) -> str:
    for bad, good in _PUNCT.items():
        text = text.replace(bad, good)
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip('"').strip()


def parse(raw: str) -> dict | None:
    """Pull {title, text} out of a model reply, JSON-fenced or not."""
    if not raw:
        return None
    body = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", body, re.DOTALL)
    if fenced:
        body = fenced.group(1).strip()
    start, end = body.find("{"), body.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(body[start : end + 1])
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict) and obj.get("text"):
            title = clean(str(obj.get("title") or "Reading practice"))
            return {"title": title[:60] or "Reading practice", "text": clean(str(obj["text"]))}
    # Nearly-JSON: a dropped brace, or an unescaped quote inside the prose. The
    # passage is sitting right there, so do not spend a retry on punctuation.
    field = re.search(r'"text"\s*:\s*"(.+?)"\s*[,}]?\s*$', body, re.DOTALL)
    if field:
        text = clean(field.group(1).replace('\\"', '"'))
        if len(_WORD.findall(text)) >= 15:
            title_match = re.search(r'"title"\s*:\s*"([^"]{1,60})"', body)
            title = clean(title_match.group(1)) if title_match else "Reading practice"
            return {"title": title or "Reading practice", "text": text}

    # No JSON at all. If the reply is plainly just the passage, take it — a model
    # that ignored the format but wrote good prose should not cost a retry.
    plain = clean(re.sub(r"^\s*(title|text)\s*:\s*", "", body, flags=re.I))
    if len(_WORD.findall(plain)) >= 20 and "{" not in plain:
        return {"title": "Reading practice", "text": plain}
    return None


class PassageService:
    """Serves a fresh passage per request, with the curated set as the floor.

    Two things make this usable in front of a learner who has just opened the
    reading tab. A small warm pool per level, because generation takes a second
    or two and nobody should watch a spinner to be handed a paragraph; and a
    hard fallback to the curated passages whenever generation is off, failing,
    or the box is busy enough that the guard has paused cold work.
    """

    def __init__(self, llm, guard, settings) -> None:
        self._llm = llm
        self._guard = guard
        self._settings = settings
        self._pool: dict[int, list[dict]] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._refills: set[asyncio.Task] = set()
        # Rotates the subject so two passages in a row are not both about food.
        self._topic_at = 0
        # What each learner last read, so a refill cannot hand back the text
        # they just finished.
        self._last: dict[str, str] = {}

    # -- public ------------------------------------------------------------
    async def get(self, level: int, *, user_id: str | None = None, seed: str | None = None) -> dict:
        level = max(0, min(int(level), max(SPECS)))
        if not self._enabled():
            return curated(level, seed=seed)

        got = self._take(level, user_id)
        if got is None:
            got = await self._generate(level)
        if got is None:
            return curated(level, seed=seed)

        if user_id:
            self._last[user_id] = got["text"]
        self._schedule_refill(level)
        return got

    def warm(self, level: int) -> None:
        """Fill this level's pool in the background, without blocking a caller."""
        if self._enabled():
            self._schedule_refill(level)

    # -- internals ---------------------------------------------------------
    # Heavy pressure only. A learner is watching a spinner for this one, so it
    # is not the deferrable background work the guard pauses at level 1 — that
    # rule is for scoring jobs nobody is waiting on. Background refills below do
    # go through the guard proper.
    PAUSE_AT_LEVEL = 3

    def _enabled(self) -> bool:
        if not getattr(self._settings, "reading_generate_passages", True):
            return False
        if self._llm is None:
            return False
        lvl = self._pressure()
        if lvl >= self.PAUSE_AT_LEVEL:
            log.info("passage_generation_skipped", reason="degradation", degradation=lvl)
            return False
        return True

    def _pressure(self) -> int:
        try:
            return int(self._guard.degradation_level) if self._guard is not None else 0
        except Exception:  # noqa: BLE001 — a guard that cannot answer is not a reason to fail
            return 0

    def _take(self, level: int, user_id: str | None) -> dict | None:
        pool = self._pool.get(level) or []
        last = self._last.get(user_id or "")
        while pool:
            candidate = pool.pop(0)
            if last is not None and candidate["text"] == last:
                continue  # the one they just read
            return candidate
        return None

    def _lock(self, level: int) -> asyncio.Lock:
        lock = self._locks.get(level)
        if lock is None:
            lock = self._locks[level] = asyncio.Lock()
        return lock

    def _schedule_refill(self, level: int) -> None:
        target = int(getattr(self._settings, "reading_passage_pool", 2))
        if target <= 0 or len(self._pool.get(level) or []) >= target:
            return
        task = asyncio.create_task(self._refill(level, target))
        # Held in a set: a bare create_task can be garbage-collected mid-flight,
        # which loses the refill silently.
        self._refills.add(task)
        task.add_done_callback(self._refills.discard)

    async def _refill(self, level: int, target: int) -> None:
        # Nobody is waiting on a refill, so it defers under any pressure the
        # guard cares about — unlike the foreground request above.
        if self._pressure() >= 1:
            return
        async with self._lock(level):
            while len(self._pool.setdefault(level, [])) < target:
                made = await self._generate(level)
                if made is None:
                    return  # generation is unhappy; the curated floor covers it
                self._pool[level].append(made)

    async def _generate(self, level: int) -> dict | None:
        attempts = int(getattr(self._settings, "reading_passage_attempts", 3))
        # The top two levels ask for a register a small model reaches for less
        # readily — the rejections there are nearly all "too easy", not "wrong" —
        # so give them room instead of raising the budget for every level.
        if level >= 4:
            attempts += 2
        for attempt in range(attempts):
            topic = TOPICS[self._topic_at % len(TOPICS)]
            self._topic_at += 1
            try:
                # Not the hot-path dialogue stage: that caps replies at 200
                # tokens because a coach answers in a sentence or two, which
                # truncated every long passage mid-JSON and read as the model
                # "failing to follow the format". A 160-word passage plus its
                # wrapper needs room.
                raw = await self._llm.chat(
                    [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": build_prompt(level, topic)},
                    ],
                    path="cold",
                    max_tokens=MAX_TOKENS,
                    # Warmer than the coach: two learners at the same level on
                    # the same day should not be handed the same paragraph.
                    temperature=0.95,
                    extra=_NO_THINKING,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("passage_generation_failed", passage_level=level, error=str(exc))
                return None
            raw = _THINK_BLOCK.sub("", raw or "")

            parsed = parse(raw)
            if parsed is None:
                log.info("passage_unparseable", passage_level=level, attempt=attempt + 1)
                continue
            ok, why = check(parsed["text"], level)
            if not ok:
                log.info("passage_off_level", passage_level=level, attempt=attempt + 1, reason=why)
                continue
            metrics = readability(parsed["text"])
            log.info(
                "passage_generated",
                passage_level=level,
                words=metrics["words"],
                ease=metrics["ease"],
                attempt=attempt + 1,
            )
            return {
                "level": level,
                "title": parsed["title"],
                "text": parsed["text"],
                "words": metrics["words"],
                "generated": True,
            }
        log.info("passage_generation_exhausted", passage_level=level, attempts=attempts)
        return None
