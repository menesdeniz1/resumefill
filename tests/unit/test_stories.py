"""STAR story bank: loading, relevance selection, prompt embedding."""


from resumefill.stories import (
    Story,
    build_stories_section,
    load_stories,
    select_relevant,
)

_STORY_A = Story(
    title="AOI system cut CAPEX by 88%",
    tags=["computer-vision", "cost-reduction"],
    situation="Commercial AOI quoted at 200k USD.",
    task="Deliver in-house alternative.",
    action="Basler line-scan cameras + custom geometry.",
    result="88% lower CAPEX, targets met.",
    reflection="Own the full stack.",
)

_STORY_B = Story(
    title="LiDAR fusion at ±3% precision",
    tags=["lidar", "sensor-fusion"],
    situation="Moving material measurement.",
    task="Four SICK LiDARs fused.",
    action="C++ calibration + error models.",
    result="±3% precision at line speed.",
)


def _write_yaml(tmp_path, content: str):
    p = tmp_path / "stories.yml"
    p.write_text(content, encoding="utf-8")
    return p


def test_missing_file_returns_empty(tmp_path):
    assert load_stories(tmp_path / "nope.yml") == []


def test_valid_yaml_loads_stories(tmp_path):
    p = _write_yaml(
        tmp_path,
        "stories:\n"
        "  - title: A\n"
        "    tags: [cv]\n"
        "    result: worked\n"
        "  - title: B\n"
        "    tags: [lidar]\n",
    )
    stories = load_stories(p)
    assert [s.title for s in stories] == ["A", "B"]


def test_malformed_yaml_returns_empty_with_warning(tmp_path, capsys):
    p = _write_yaml(tmp_path, "stories: [broken: yaml: here\n")
    assert load_stories(p) == []
    err = capsys.readouterr().err
    assert "Could not parse" in err


def test_invalid_entries_skipped_others_kept(tmp_path, capsys):
    p = _write_yaml(
        tmp_path,
        "stories:\n"
        "  - title: Valid One\n"
        "  - not_a_dict\n"
        "  - tags: [no-title]\n"
        "  - title: Valid Two\n",
    )
    stories = load_stories(p)
    assert [s.title for s in stories] == ["Valid One", "Valid Two"]


def test_select_relevant_matches_jd_tokens():
    jd = "We need computer-vision and cost-reduction experience for factory inspection."
    selected = select_relevant([_STORY_B, _STORY_A], jd)
    assert selected[0] is _STORY_A
    assert len(selected) == 1  # story B has zero overlap


def test_select_relevant_caps_at_k():
    jd = "computer-vision lidar sensor-fusion cost-reduction"
    selected = select_relevant([_STORY_B, _STORY_A], jd, k=1)
    assert len(selected) == 1


def test_irrelevant_jd_selects_nothing():
    assert select_relevant([_STORY_A, _STORY_B], "Sales role selling insurance policies") == []


def test_build_section_embeds_story_details():
    section = build_stories_section([_STORY_A])
    assert "RELEVANT STAR STORIES" in section
    assert "AOI system cut CAPEX by 88%" in section
    assert "Situation:" in section and "Reflection:" in section


def test_build_section_empty_when_no_stories():
    assert build_stories_section([]) == ""
