"""Unit tests for the MessageReaderNode pickle gate (no Flask involved).

pickle.load can execute arbitrary code, so MessageReaderNode must refuse to
read pickle files (explicit format or auto-detected from .pkl/.pickle
extensions) unless the 'allow_pickle' config is enabled.
"""

import pickle

import pytest

from pynode.nodes.MessageWriterNode.messagereader_node import MessageReaderNode


class _ErrorCapturingEngine:
    """Minimal stand-in for WorkflowEngine that records broadcast errors."""

    def __init__(self):
        self.errors = []

    def broadcast_error(self, source_node_id, source_node_name, error_msg):
        self.errors.append(error_msg)


@pytest.fixture
def pickle_file(tmp_path):
    path = tmp_path / 'data.pkl'
    with open(path, 'wb') as f:
        pickle.dump({'answer': 42, 'items': [1, 2, 3]}, f)
    return path


@pytest.fixture
def reader():
    node = MessageReaderNode()
    node.set_workflow_engine(_ErrorCapturingEngine())
    return node


def test_pickle_blocked_by_default_auto_detect(reader, pickle_file):
    # Default config: input_format='auto' -> .pkl auto-detects as pickle
    assert reader.get_config_bool('allow_pickle', False) is False
    data = reader._read_file_data(str(pickle_file))
    assert data is None
    errors = reader._workflow_engine.errors
    assert len(errors) == 1
    assert 'Pickle loading disabled' in errors[0]
    assert 'Allow Pickle Loading' in errors[0]


def test_pickle_blocked_by_default_explicit_format(reader, pickle_file):
    reader.configure({'input_format': 'pickle'})
    data = reader._read_file_data(str(pickle_file))
    assert data is None
    assert len(reader._workflow_engine.errors) == 1


def test_pickle_loads_when_allowed(reader, pickle_file):
    reader.configure({'allow_pickle': True})
    data = reader._read_file_data(str(pickle_file))
    assert data == {'answer': 42, 'items': [1, 2, 3]}
    assert reader._workflow_engine.errors == []


def test_pickle_loads_when_allowed_string_config(reader, pickle_file):
    # Config values arrive from the UI as strings; get_config_bool handles both
    reader.configure({'allow_pickle': 'true', 'input_format': 'pickle'})
    data = reader._read_file_data(str(pickle_file))
    assert data == {'answer': 42, 'items': [1, 2, 3]}


def test_non_pickle_formats_unaffected(reader, tmp_path):
    json_file = tmp_path / 'data.json'
    json_file.write_text('{"a": 1}', encoding='utf-8')
    data = reader._read_file_data(str(json_file))
    assert data == {'a': 1}
    assert reader._workflow_engine.errors == []
