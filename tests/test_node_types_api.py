"""Tests for /api/node-types palette ordering.

Asserts the category ordering served to the frontend palette follows the
configured Node-RED-style order, that category matching is case-insensitive
(opencv nodes land in the opencv bucket, not the unknown bucket), and that
nodes are alphabetized within each category.
"""

from pynode import node_registry

# Must match category_order in pynode/node_registry.py (lowercased).
EXPECTED_CATEGORY_ORDER = [
    'common',
    'input',
    'output',
    'function',
    'logic',
    'network',
    'vision',
    'analysis',
    'node probes',
    'opencv',
]


def _get_types(api_client):
    resp = api_client.get('/api/node-types')
    assert resp.status_code == 200
    types = resp.get_json()
    assert isinstance(types, list) and len(types) > 0
    return types


def _distinct_categories_in_order(types):
    seen = []
    for t in types:
        cat = str(t['category']).lower()
        if cat not in seen:
            seen.append(cat)
    return seen


def test_node_types_categories_follow_configured_order(api_client):
    types = _get_types(api_client)
    seen = _distinct_categories_in_order(types)

    known = [c for c in seen if c in EXPECTED_CATEGORY_ORDER]
    # Known categories arrive exactly in the configured relative order
    assert known == [c for c in EXPECTED_CATEGORY_ORDER if c in known]

    # Every known category comes before any unknown (custom/system) category
    if any(c not in EXPECTED_CATEGORY_ORDER for c in seen):
        first_unknown = next(
            i for i, c in enumerate(seen) if c not in EXPECTED_CATEGORY_ORDER
        )
        assert all(c in EXPECTED_CATEGORY_ORDER for c in seen[:first_unknown])
        assert all(c not in EXPECTED_CATEGORY_ORDER for c in seen[first_unknown:])


def test_opencv_nodes_sort_into_opencv_bucket_despite_case(api_client):
    """Nodes declaring category 'opencv' (any case) must land in the opencv
    bucket (second to last known category), not fall to the unknown bucket."""
    types = _get_types(api_client)

    opencv_idxs = [
        i for i, t in enumerate(types) if str(t['category']).lower() == 'opencv'
    ]
    assert opencv_idxs, 'expected opencv-category nodes to be present'

    # opencv nodes form one contiguous bucket
    assert opencv_idxs == list(range(opencv_idxs[0], opencv_idxs[-1] + 1))

    # ...positioned after every other known category...
    for i, t in enumerate(types):
        cat = str(t['category']).lower()
        if cat in EXPECTED_CATEGORY_ORDER and cat != 'opencv':
            assert i < opencv_idxs[0], (
                f"{t['type']} ({cat}) should come before the opencv bucket"
            )

    # ...and before any unknown-category (custom/system) node
    unknown_idxs = [
        i for i, t in enumerate(types)
        if str(t['category']).lower() not in EXPECTED_CATEGORY_ORDER
    ]
    if unknown_idxs:
        assert opencv_idxs[-1] < min(unknown_idxs)


def test_node_probes_between_analysis_and_opencv(api_client):
    types = _get_types(api_client)
    seen = _distinct_categories_in_order(types)
    assert 'node probes' in seen
    if 'analysis' in seen:
        assert seen.index('analysis') < seen.index('node probes')
    if 'opencv' in seen:
        assert seen.index('node probes') < seen.index('opencv')


def test_no_ai_category_remains(api_client):
    """The one-node 'AI' category was merged into 'vision'."""
    types = _get_types(api_client)
    assert all(str(t['category']).lower() != 'ai' for t in types)
    # The vLLM node itself is now in vision
    vllm = [t for t in types if t['type'] == 'VLLMNode']
    if vllm:
        assert vllm[0]['category'] == 'vision'


def test_nodes_alphabetized_within_each_category(api_client):
    types = _get_types(api_client)
    runs = {}
    for t in types:
        runs.setdefault(str(t['category']).lower(), []).append(t['name'])
    for cat, names in runs.items():
        assert names == sorted(names, key=lambda n: (n.lower(), n)), (
            f'nodes in category {cat!r} are not alphabetized: {names}'
        )


def test_registry_cache_matches_api(api_client):
    """The API serves the shared node_registry cache."""
    types = _get_types(api_client)
    cached = node_registry.get_node_types()
    assert [t['type'] for t in types] == [t['type'] for t in cached]
