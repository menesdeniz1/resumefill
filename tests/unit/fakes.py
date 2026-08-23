"""Shared test doubles for LLM interactions."""

from __future__ import annotations


class FakeLLM:
    """Scripted LLM: pops scripted outcomes per call, records prompts."""

    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.calls: list[str] = []

    def invoke(self, prompt):
        self.calls.append(prompt)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeResponse:
    def __init__(self, content):
        self.content = content
