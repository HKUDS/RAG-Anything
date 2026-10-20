from raganything.modalprocessors import BaseModalProcessor


def parse(response):
    processor = BaseModalProcessor.__new__(BaseModalProcessor)
    return processor._robust_json_parse(response)


def test_single_backslash_latex_is_kept():
    result = parse(
        r'{"detailed_description": "x = \frac{a}{b} + \beta",'
        r' "entity_info": {"entity_name": "eq", "entity_type": "equation",'
        r' "summary": "uses \frac"}}'
    )
    assert result["detailed_description"] == r"x = \frac{a}{b} + \beta"
    assert result["entity_info"]["summary"] == r"uses \frac"


def test_escaped_backslash_latex_is_unchanged():
    result = parse(r'{"detailed_description": "x = \\frac{a}{b} + \\beta"}')
    assert result["detailed_description"] == r"x = \frac{a}{b} + \beta"


def test_lone_control_characters_are_not_touched():
    result = parse(r'{"detailed_description": "a\f1 b\b "}')
    assert result["detailed_description"] == "a\f1 b\b "
