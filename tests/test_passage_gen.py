"""The difficulty gate on generated reading passages.

The point of these is not that the model writes well — it is that a passage
which lands at the wrong level never reaches a learner, and that the exercise
still works when the model is unavailable.
"""

from __future__ import annotations

import json

import pytest

from backend.coldpath.passage_gen import (
    SPECS,
    PassageService,
    build_prompt,
    check,
    count_syllables,
    parse,
    readability,
)

BEGINNER = (
    "I wake up early. I eat bread and drink tea. Then I walk to the shop near my "
    "house. The sun is warm today. I like this time of the day."
)
ADVANCED = (
    "Urbanisation rarely proceeds according to any coherent municipal design; rather, "
    "settlements accrete around opportunity, and the infrastructure that subsequently "
    "materialises is invariably a negotiated compromise between competing interests "
    "whose priorities were never reconcilable in the first instance."
)


def as_reply(title: str, text: str) -> str:
    """What the model is supposed to hand back."""
    return json.dumps({"title": title, "text": text})


class FakeLLM:
    """Returns queued replies; records the prompts and the token budget asked for."""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.max_tokens: list[int] = []

    async def chat(self, messages, *, path="hot", max_tokens=512, temperature=0.7, extra=None):
        self.prompts.append(messages[-1]["content"])
        self.max_tokens.append(max_tokens)
        return self.replies.pop(0) if self.replies else ""


class FakeGuard:
    def __init__(self, level: int = 0):
        self.degradation_level = level


class Settings:
    reading_generate_passages = True
    reading_passage_pool = 0  # no background refill inside a test
    reading_passage_attempts = 3


def test_syllables_handles_silent_e():
    assert count_syllables("cake") == 1
    assert count_syllables("water") == 2
    assert count_syllables("little") == 2
    # Four, not five: the heuristic counts vowel groups, so the "ia" in
    # ne-go-ti-a-ted merges. Close enough for a ratio against a wide band.
    assert count_syllables("negotiated") == 4


def test_readability_separates_the_two_extremes():
    easy, hard = readability(BEGINNER), readability(ADVANCED)
    assert easy["ease"] > hard["ease"]
    assert easy["avg_sentence"] < hard["avg_sentence"]
    assert easy["hard_word_ratio"] < hard["hard_word_ratio"]


def test_beginner_text_is_rejected_at_the_top_level():
    # Too short and far too easy to be a level-5 passage.
    ok, why = check(BEGINNER, 5)
    assert not ok and why


def test_advanced_text_is_rejected_at_the_bottom_level():
    ok, why = check(ADVANCED, 0)
    assert not ok and why


@pytest.mark.parametrize("level", sorted(SPECS))
def test_every_level_states_a_usable_band(level):
    spec = SPECS[level]
    lo, hi = spec.words
    assert 0 < lo < hi
    assert spec.ease[0] < spec.ease[1]
    assert str(level) in build_prompt(level, "food and cooking")


def test_parse_reads_json_fenced_or_bare():
    fenced = parse('```json\n{"title": "The walk", "text": "I walk to work."}\n```')
    assert fenced == {"title": "The walk", "text": "I walk to work."}
    bare = parse('{"title": "A", "text": "Some words here."}')
    assert bare and bare["text"] == "Some words here."


def test_parse_normalises_typographic_punctuation():
    # A curly apostrophe would be matched word-by-word against a transcript that
    # has a straight one, and read as a mistake the learner cannot see.
    got = parse('{"title": "T", "text": "It’s a long — quiet — road."}')
    assert got is not None
    assert "’" not in got["text"] and "—" not in got["text"]


def test_parse_accepts_a_reply_that_is_just_the_prose():
    got = parse(
        "The market opens early on Friday and the street fills with people "
        "quickly, so my neighbour always arrives before the heat becomes hard "
        "to bear."
    )
    assert got is not None and got["title"] == "Reading practice"


@pytest.mark.asyncio
async def test_off_level_candidate_is_rejected_then_regenerated():
    good = as_reply("Morning", BEGINNER)
    llm = FakeLLM([as_reply("Too hard", ADVANCED), good])
    svc = PassageService(llm, FakeGuard(), Settings())

    got = await svc.get(0)

    assert got["generated"] is True
    assert got["text"] == BEGINNER
    assert len(llm.prompts) == 2  # the first candidate was thrown away


@pytest.mark.asyncio
async def test_falls_back_to_curated_when_generation_keeps_missing():
    llm = FakeLLM([as_reply("x", ADVANCED)] * 3)
    svc = PassageService(llm, FakeGuard(), Settings())

    got = await svc.get(0)

    assert got.get("generated") is not True
    assert got["text"] and got["level"] == 0


@pytest.mark.asyncio
async def test_falls_back_when_the_model_raises():
    class Broken:
        async def chat(self, *a, **k):
            raise RuntimeError("llm is down")

    got = await PassageService(Broken(), FakeGuard(), Settings()).get(2)

    assert got.get("generated") is not True
    assert got["level"] == 2


@pytest.mark.asyncio
async def test_generation_is_skipped_under_heavy_pressure():
    llm = FakeLLM([as_reply("Morning", BEGINNER)])
    svc = PassageService(llm, FakeGuard(level=PassageService.PAUSE_AT_LEVEL), Settings())

    got = await svc.get(0)

    assert got.get("generated") is not True
    assert llm.prompts == []  # the model was never asked


@pytest.mark.asyncio
async def test_moderate_pressure_still_serves_a_learner_a_fresh_passage():
    # Level 1 pauses background scoring, but somebody is watching a spinner for
    # this one — falling back to a memorised text is the worse outcome.
    llm = FakeLLM([as_reply("Morning", BEGINNER)])
    svc = PassageService(llm, FakeGuard(level=1), Settings())

    got = await svc.get(0)

    assert got["generated"] is True


@pytest.mark.asyncio
async def test_a_learner_is_not_handed_the_text_they_just_read():
    other = "The bus is late again. I wait by the door and read my book until it comes."
    llm = FakeLLM(
        [as_reply("A", BEGINNER), as_reply("B", other)]
    )
    svc = PassageService(llm, FakeGuard(), Settings())

    first = await svc.get(0, user_id="abu_ali")
    svc._pool[0] = [dict(first)]  # the pool happens to hold the same text
    second = await svc.get(0, user_id="abu_ali")

    assert second["text"] != first["text"]


@pytest.mark.asyncio
async def test_generation_asks_for_room_to_write_a_long_passage():
    """The hot-path stage caps replies at 200 tokens, which is a sentence or
    two. Generating through it truncated every level-4 and level-5 passage
    mid-JSON, and the logs blamed the model for ignoring the format."""
    llm = FakeLLM([as_reply("Morning", BEGINNER)])
    await PassageService(llm, FakeGuard(), Settings()).get(0)

    assert llm.max_tokens and min(llm.max_tokens) >= 400


@pytest.mark.asyncio
async def test_a_reasoning_block_is_not_read_as_the_passage():
    llm = FakeLLM(["<think>Let me plan this out first.</think>" + as_reply("M", BEGINNER)])
    got = await PassageService(llm, FakeGuard(), Settings()).get(0)

    assert got["generated"] is True and "think" not in got["text"]
