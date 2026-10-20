from raganything.modalprocessors import (
    BaseModalProcessor,
    EquationModalProcessor,
    ImageModalProcessor,
)


def processor(cls):
    return cls.__new__(cls)


TRUNCATED = [
    '{"detailed_description": "A bar chart of revenue by quarter", "entity_info": {"entity_na',
    '{"detailed_description": "A photo of a bridge at night", "entity_info": {',
]


def test_regex_fallback_keeps_found_entity_name():
    result = processor(BaseModalProcessor)._robust_json_parse(
        '{"detailed_description": "chart", "entity_info": {"entity_name": "Revenue",'
        ' "entity_type": "image", "summary": "rev'
    )
    assert result["entity_info"]["entity_name"] == "Revenue"


def test_truncated_responses_get_distinct_entity_names():
    image = processor(ImageModalProcessor)
    results = [image._parse_response(r) for r in TRUNCATED]
    assert results[0][0] == "A bar chart of revenue by quarter"
    assert results[0][1]["entity_name"] != results[1][1]["entity_name"]

    equation = processor(EquationModalProcessor)
    names = {equation._parse_equation_response(r)[1]["entity_name"] for r in TRUNCATED}
    assert len(names) == 2
