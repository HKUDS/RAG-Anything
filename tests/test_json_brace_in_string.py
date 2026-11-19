import json

import pytest

from raganything.modalprocessors import BaseModalProcessor


@pytest.mark.parametrize(
    "description",
    [
        "A code snippet ending with }",
        "A code snippet starting with {",
        'An escaped quote " followed by }',
        "A normal image description",
        "A path ending with a backslash \\",
    ],
)
@pytest.mark.parametrize("prefix", ["", "Here is the response: ", "A stray } before: "])
def test_json_braces_in_strings(description, prefix):
    processor = BaseModalProcessor.__new__(BaseModalProcessor)
    expected = {
        "detailed_description": description,
        "entity_info": {
            "entity_name": "figure",
            "entity_type": "image",
            "summary": "example",
        },
    }
    serialized = json.dumps(expected)
    response = prefix + serialized + (" End of response." if prefix else "")

    assert processor._robust_json_parse(response) == expected
    assert processor._extract_all_json_candidates(response)[0] == serialized
