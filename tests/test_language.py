"""language policy tests."""

from __future__ import annotations

from wiki_cli import language


def test_language_policy_defaults_to_korean_body_and_original_headings(monkeypatch):
    monkeypatch.delenv("WIKI_OUTPUT_LANGUAGE", raising=False)
    monkeypatch.delenv("WIKI_HEADING_ORIGINAL_LANGUAGE", raising=False)

    policy = language.language_policy()

    assert "body prose in Korean" in policy
    assert "headings in the source/original language" in policy
    assert language.heading_label("요약", "Summary") == "Summary"


def test_language_policy_can_use_english_output(monkeypatch):
    monkeypatch.setenv("WIKI_OUTPUT_LANGUAGE", "en")

    policy = language.language_policy(answer=True)

    assert "Answer in English" in policy
    assert language.heading_label("요약", "Summary") == "Summary"


def test_heading_original_language_overrides_body_language(monkeypatch):
    monkeypatch.setenv("WIKI_OUTPUT_LANGUAGE", "ko")
    monkeypatch.setenv("WIKI_HEADING_ORIGINAL_LANGUAGE", "on")

    policy = language.language_policy()

    assert "headings in the source/original language" in policy
    assert language.heading_label("요약", "Summary") == "Summary"
