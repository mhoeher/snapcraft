# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2018-2019 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import collections
import logging
from typing import Any, Dict, Optional, TextIO, Union

import yaml

from snapcraft.errors import SnapcraftError

logger = logging.getLogger(__name__)

try:
    # The C-based loaders/dumpers aren't available everywhere, but they're much faster.
    # Use them if possible. If not, we could fallback to the normal loader/dumper, but
    # they actually behave differently, so raise an error instead.
    from yaml import CSafeDumper, CSafeLoader  # type: ignore
except ImportError:
    raise RuntimeError("Snapcraft requires PyYAML to be built with libyaml bindings")


class YamlValidationError(SnapcraftError):
    fmt = "Issues while validating {source}: {message}"


def load(stream: Union[TextIO, str]) -> Any:
    """Safely load YAML in ordered manner."""

    class YamlLoader(_SafeOrderedLoader):
        pass

    return yaml.load(stream, Loader=_SafeOrderedLoader)


def dump(
    data: Union[Dict[str, Any], yaml.YAMLObject],
    *,
    stream: Optional[TextIO] = None,
    sort_keys=True
) -> Optional[str]:
    """Safely dump YAML in ordered manner."""
    return yaml.dump(
        data,
        stream=stream,
        Dumper=_SafeOrderedDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=sort_keys,
    )


class _SafeOrderedLoader(CSafeLoader):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.add_constructor(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _dict_constructor
        )


class _SafeOrderedDumper(CSafeDumper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_representer(str, _str_presenter)
        self.add_representer(collections.OrderedDict, _dict_representer)


class SnapcraftYAMLObject(yaml.YAMLObject):
    yaml_loader = _SafeOrderedLoader
    yaml_dumper = _SafeOrderedDumper

    # We could implement a from_yaml class method here which would force loading to
    # go through constructors, but our previous method of doing that has been broken
    # long enough that it would require a larger change.


def _dict_representer(dumper, data):
    return dumper.represent_dict(data.items())


def _check_duplicate_keys(loader, node):
    mappings = set()

    for key_node, value_node in node.value:
        try:
            if key_node.value in mappings:
                logger.warning("Duplicate key in YAML detected: %r", key_node.value)
            else:
                mappings.add(key_node.value)
        except TypeError:
            # Ignore errors for malformed inputs that will be caught later.
            pass


def _dict_constructor(loader, node):
    _check_duplicate_keys(loader, node)

    # Necessary in order to make yaml merge tags work
    loader.flatten_mapping(node)
    value = loader.construct_pairs(node)

    try:
        return collections.OrderedDict(value)
    except TypeError:
        raise yaml.constructor.ConstructorError(
            "while constructing a mapping",
            node.start_mark,
            "found unhashable key",
            node.start_mark,
        )


def _str_presenter(dumper, data):
    if len(data.splitlines()) > 1:  # check for multiline string
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


class OctInt(SnapcraftYAMLObject):
    """An int represented in octal form."""

    yaml_tag = u"!OctInt"

    def __init__(self, value):
        super().__init__()
        self._value = value

    @classmethod
    def to_yaml(cls, dumper, data):
        """
        Convert a Python object to a representation node.
        """
        return dumper.represent_scalar(
            "tag:yaml.org,2002:int", "{:04o}".format(data._value)
        )
