from app.domain import StageContext, stage_id_from_path


def test_stage_id_is_extracted_only_from_supported_media_path() -> None:
    assert stage_id_from_path("live/stage-1") == "1"
    assert stage_id_from_path("live/stage-main_hall") == "main_hall"
    assert stage_id_from_path("live/stage-../../etc") is None
    assert stage_id_from_path("other/stage-1") is None


def test_stage_context_has_safe_defaults() -> None:
    context = StageContext(id="7", name="Stage 7")
    assert context.languages == ["es"]
    assert context.glossary == []

