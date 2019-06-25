import os

import six

if six.PY3:
    from unittest.mock import patch
else:
    from mock import patch

import pytest
import yaml
from pybatfish.client.session import Session

from module_utils.bf_util import (
    get_facts,
    _encapsulate_nodes_facts, get_node_count, load_facts, validate_facts,
    write_facts, _unencapsulate_facts, assert_dict_subset)
from tests.unit.test_utils import MockTableAnswer, MockQuestion


def test_get_facts_questions():
    """Test that get facts calls the right questions, passing through the right args."""
    bf = Session(load_questions=False)
    nodes = 'foo'
    with patch.object(bf.q,
                      'nodeProperties',
                      create=True) as mock_node, \
            patch.object(bf.q,
                         'interfaceProperties',
                         create=True) as mock_iface, \
            patch.object(bf.q,
                         'bgpPeerConfiguration',
                         create=True) as mock_peers, \
            patch.object(bf.q,
                         'bgpProcessConfiguration',
                         create=True) as mock_proc:
        mock_node.return_value = MockQuestion(MockTableAnswer())
        mock_iface.return_value = MockQuestion(MockTableAnswer())
        mock_proc.return_value = MockQuestion(MockTableAnswer())
        mock_peers.return_value = MockQuestion(MockTableAnswer())
        get_facts(bf, nodes)

        mock_node.assert_called_with(nodes=nodes)
        mock_iface.assert_called_with(nodes=nodes)
        mock_proc.assert_called_with(nodes=nodes)
        mock_peers.assert_called_with(nodes=nodes)


def test_get_node_count():
    """Test that node count is correctly extracted."""
    version = "fake_version"
    no_nodes = _encapsulate_nodes_facts({}, version)
    one_node = _encapsulate_nodes_facts({'node1': 'blah'}, version)
    two_nodes = _encapsulate_nodes_facts({'node1': 'blah',
                                          'node2': 'blah'}, version)

    assert get_node_count(no_nodes) == 0
    assert get_node_count(one_node) == 1
    assert get_node_count(two_nodes) == 2


def test_load_facts(tmpdir):
    """Test that load_facts correctly loads facts from a fact directory."""
    version = 'fake_version'
    node1 = {
        'node1': 'foo'
    }
    node2 = {
        'node2': 'foo'
    }
    tmpdir.join('node1.yml').write(_encapsulate_nodes_facts(node1, version))
    tmpdir.join('node2.yml').write(_encapsulate_nodes_facts(node2, version))
    facts = load_facts(str(tmpdir))

    # Confirm facts were loaded from both files
    assert facts == _encapsulate_nodes_facts({'node1': 'foo', 'node2': 'foo'},
                                             version)


def test_load_facts_bad_dir(tmpdir):
    """Test load facts when loading from bad directories."""
    # Empty input dir should throw ValueError
    with pytest.raises(ValueError) as e:
        load_facts(str(tmpdir))
    assert 'No files present in specified dir' in str(e)

    f = tmpdir.join('file')
    f.write('foo')
    # File instead of dir should throw exception indicating such
    with pytest.raises(OSError) as e_not_dir:
        load_facts(str(f))
    assert 'Not a directory' in str(e_not_dir)


def test_load_facts_mismatch_version(tmpdir):
    """Test load facts when loaded nodes have different format versions."""
    version1 = 'version1'
    node1 = {
        'node1': 'foo'
    }
    version2 = 'version2'
    node2 = {
        'node2': 'foo'
    }
    tmpdir.join('node1.yml').write(_encapsulate_nodes_facts(node1, version1))
    tmpdir.join('node2.yml').write(_encapsulate_nodes_facts(node2, version2))
    with pytest.raises(ValueError) as e:
        load_facts(str(tmpdir))
    assert 'Input file version mismatch' in str(e)


def test_validate_facts():
    """Test that fact validation works for matching facts."""
    expected = {
        'node1': {'foo': 1},
        'node2': {'foo': 2},
    }
    actual = {
        'node1': {'foo': 1},
        'node2': {'foo': 2},
        'node3': {'foo': 3},
    }
    version = 'fake_version'
    res = validate_facts(_encapsulate_nodes_facts(expected, version),
                         _encapsulate_nodes_facts(actual, version))
    # No results from matching (subset) expected and actual
    assert len(res) == 0


def test_validate_facts_not_matching_version():
    """Test that fact validation detects mismatched versions."""
    expected = {
        'node1': {'foo': 1},
        'node2': {'foo': 2},
    }
    actual = {
        'node1': {'foo': 1},
        'node2': {'foo': 2},
        'node3': {'foo': 3},
    }
    version_expected = 'correct_version'
    version_actual = 'fake_version'
    res = validate_facts(_encapsulate_nodes_facts(expected, version_expected),
                         _encapsulate_nodes_facts(actual, version_actual))
    # One result per expected node for mismatched version
    assert len(res) == len(expected)
    for node in expected:
        # Make sure version mismatch details are in results details
        assert res[node] == {
            'Version': {
                'actual': version_actual,
                'expected': version_expected,
            }
        }


def test_validate_facts_not_matching_data():
    """Test that fact validation works for mismatched facts."""
    expected = {
        'node1': {'foo': 1, 'bar': 1, 'baz': 1},
        'node2': {'foo': 2},
    }
    actual = {
        'node1': {'foo': 0, 'bar': 1},  # 'foo' doesn't match expected
        # also missing 'baz': 1
        'node2': {'foo': 2},
        'node3': {'foo': 3},
    }
    version = 'version'
    res = validate_facts(_encapsulate_nodes_facts(expected, version),
                         _encapsulate_nodes_facts(actual, version))

    # Result should identify the mismatched value and the missing key
    assert res['node1'] == {
        'foo': {
            'expected': 1,
            'actual': 0,
        },
        'baz': {
            'expected': 1,
            'key_present': False,
        }
    }


def test_write_facts(tmpdir):
    """Test that writing facts writes nodes' facts to individual files."""
    nodes = {'node1': 'foo', 'node2': 'bar'}
    version = 'version'
    facts = _encapsulate_nodes_facts(nodes, version)
    write_facts(str(tmpdir), facts)
    for node in nodes:
        filename = node + '.yml'
        file_path = str(tmpdir.join(filename))
        assert os.path.isfile(file_path)
        with open(file_path) as f:
            node_facts_raw = yaml.safe_load(f.read())
            node_facts, node_version = _unencapsulate_facts(node_facts_raw)
            assert version == node_version, 'Each file has the correct version'
            assert node_facts.get(node) == nodes[
                node], 'Each file has the correct facts'


def test_assert_dict_subset_equal():
    """Test that assert_dict_subset correctly identifies equal dicts."""
    actual = {
        'key': 'value',
        'parent_key': {
            'nested_key': 'nested_value',
        },
        'list': ['foo'],
        'empty_list': [],
        'none': None,
    }
    expected = {
        'key': 'value',
        'parent_key': {
            'nested_key': 'nested_value',
        },
        'list': ['foo'],
        'empty_list': [],
        'none': None,
    }
    # Equal dicts should result in no differences
    assert assert_dict_subset(actual, expected) == {}


def test_assert_dict_subset_subset():
    """Test that assert_dict_subset correctly identifies expected as a subset of actual."""
    actual = {
        'key': 'value',
        'key2': 'value2',
        'parent_key': {
            'nested_key': 'nested_value',
            'nested_key2': 'nested_value2',
        },
    }
    expected = {
        'key': 'value',
        'parent_key': {
            'nested_key': 'nested_value',
        },
    }
    # Expected being a subset should result in no differences
    assert assert_dict_subset(actual, expected) == {}


def test_assert_dict_subset_not_equal():
    """Test that assert_dict_subset correctly identifies when expected is not a subset of actual."""
    actual = {
        'key': 'value',
        'key2': 'value2',
        'parent_key': {
            'nested_key': 'nested_value',
            'nested_key2': 'nested_value2',
            'different_nested_key': 'not_different_value',
        },
        'different_key': 'not_different_value',
    }
    expected = {
        'key': 'value',
        'parent_key': {
            'nested_key': 'nested_value',
            'missing_nested_key': 'missing_value',
            'different_nested_key': 'different_value',
        },
        'missing_key': 'missing_value',
        'different_key': 'different_value',

    }
    # Make sure we identify missing and different values
    assert assert_dict_subset(actual, expected) == {
        'parent_key.missing_nested_key': {
            'expected': 'missing_value',
            'key_present': False,
        },
        'parent_key.different_nested_key': {
            'expected': 'different_value',
            'actual': 'not_different_value',
        },
        'missing_key': {
            'expected': 'missing_value',
            'key_present': False,
        },
        'different_key': {
            'expected': 'different_value',
            'actual': 'not_different_value',
        }
    }