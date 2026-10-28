"""The owner's scripted answers, and the stand-in that gives them to a system under test."""
from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from keryx_bench.sessions import remove_session_dir


@dataclass(frozen=True)
class Answer:
    about: str
    answer: str


@dataclass(frozen=True)
class OwnerScript:
    autonomy: str
    answers: tuple[Answer, ...]
    default: str


def load_owner(path: Path) -> OwnerScript:
    raw = yaml.safe_load(path.read_text()) or {}
    missing = [key for key in ("autonomy", "default") if not raw.get(key)]
    if missing:
        raise ValueError(f"{path}: owner script needs {', '.join(missing)}")
    answers = tuple(Answer(about=str(a["about"]), answer=str(a["answer"])) for a in raw.get("answers") or [])
    return OwnerScript(autonomy=str(raw["autonomy"]), answers=answers, default=str(raw["default"]))


class Matcher(Protocol):
    async def pick(self, question: str, script: OwnerScript) -> str | None: ...


class KeywordMatcher:
    """Deterministic matcher for tests: every word of `about` must occur in the question."""

    async def pick(self, question: str, script: OwnerScript) -> str | None:
        text = question.lower()
        for answer in script.answers:
            if all(word in text for word in answer.about.lower().split()):
                return answer.answer
        return None


async def _ask_model(prompt: str, model: str) -> str:
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    with tempfile.TemporaryDirectory(prefix="keryx-judge-") as cwd:
        cwd = os.path.realpath(cwd)
        options = ClaudeAgentOptions(
            cwd=cwd, model=model, setting_sources=[], strict_mcp_config=True, mcp_servers={},
            tools=[], max_turns=1, env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},
        )
        result = ""
        try:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, ResultMessage):
                    result = message.result or ""
        finally:
            remove_session_dir(cwd, must_contain="keryx-judge-")
    return result.strip()


class ModelMatcher:
    """Lets a cheap model pick one of the owner's scripted answers; it never writes an answer itself."""

    def __init__(self, model: str = "haiku"):
        self.model = model

    async def pick(self, question: str, script: OwnerScript) -> str | None:
        if not script.answers:
            return None
        listed = "\n".join(f"{i}. about: {a.about} | answer: {a.answer}" for i, a in enumerate(script.answers, 1))
        reply = await _ask_model(
            "You map a question to an owner's scripted answers.\n"
            f"Scripted answers:\n{listed}\n\nQuestion:\n{question[-6000:]}\n\n"
            "Reply with only the number of the scripted answer that answers this question, or NONE.",
            self.model,
        )
        found = re.match(r"\s*(\d+)", reply)
        if found and 1 <= int(found.group(1)) <= len(script.answers):
            return script.answers[int(found.group(1)) - 1].answer
        return None


async def model_says_yes(question: str, text: str, model: str = "haiku") -> bool:
    reply = await _ask_model(f"Answer only YES or NO.\nQuestion: {question}\n\nText:\n{text[-6000:]}", model)
    return reply.upper().startswith("YES")


class StandIn:
    """Plays the owner during a replay: answers only from the script, counts every interruption."""

    def __init__(self, script: OwnerScript, matcher: Matcher):
        self.script = script
        self.matcher = matcher
        self.interruptions = 0
        self.unanswered: list[str] = []

    @property
    def fallback(self) -> str:
        return f"{self.script.autonomy} {self.script.default}"

    async def answer(self, questions: list[dict]) -> dict[str, str]:
        self.interruptions += 1
        answers = {}
        for q in questions:
            picked = await self.matcher.pick(q["question"], self.script)
            if picked is None:
                self.unanswered.append(q["question"])
            answers[q["question"]] = picked or self.fallback
        return answers

    async def on_stop(self, final_text: str, is_question: Callable[[str], Awaitable[bool]]) -> str | None:
        # A message without a question mark asks nothing; the judge only settles the ones that might.
        if "?" not in final_text or not await is_question(final_text):
            return None
        self.interruptions += 1
        picked = await self.matcher.pick(final_text, self.script)
        if picked is None:
            self.unanswered.append(final_text[-500:])
        return picked or self.fallback
