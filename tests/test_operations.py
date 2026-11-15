"""OperationKind derives identity and exclusivity from class hierarchy."""

from formbridge.operations import ExclusiveKind, OperationKind


class NormalKind(OperationKind):
    pass


class ExclusiveWork(OperationKind, ExclusiveKind):
    pass


class ChildOfNormal(NormalKind):
    pass


def test_group_derived_from_class_name():
    assert NormalKind.group == f"{NormalKind.__module__}.{NormalKind.__qualname__}"
    assert ExclusiveWork.group != NormalKind.group


def test_exclusive_from_mixin():
    assert NormalKind.exclusive is False
    assert ExclusiveWork.exclusive is True


def test_child_inherits_non_exclusive():
    assert ChildOfNormal.exclusive is False
    assert ChildOfNormal.group != NormalKind.group


def test_each_class_has_unique_group():
    groups = {NormalKind.group, ExclusiveWork.group, ChildOfNormal.group}
    assert len(groups) == 3
