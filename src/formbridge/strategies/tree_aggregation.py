"""Recursive tree aggregation policies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping, Sequence


class TreeAggregationPolicyABC(ABC):
    """Aggregation policy for a tree node."""

    @abstractmethod
    def aggregate(self, node_percent: float, children: Sequence[float]) -> float:
        """Return aggregated percent for this node."""


class MeanTreeAggregationPolicy(TreeAggregationPolicyABC):
    """Arithmetic mean over children."""

    def aggregate(self, node_percent: float, children: Sequence[float]) -> float:
        if not children:
            return 0.0
        return sum(children) / len(children)


class ExplicitPercentTreeAggregationPolicy(TreeAggregationPolicyABC):
    """Use node-local percent directly."""

    def aggregate(self, node_percent: float, children: Sequence[float]) -> float:
        return node_percent


@dataclass(frozen=True)
class TreeAggregationPolicyRegistry:
    """Typed policy registry with fail-loud lookups."""

    policies: Mapping[str, TreeAggregationPolicyABC]

    def aggregate(
        self,
        policy_id: str,
        node_percent: float,
        children: Sequence[float],
    ) -> float:
        if policy_id not in self.policies:
            raise ValueError(f"Unknown tree aggregation policy '{policy_id}'")
        return self.policies[policy_id].aggregate(node_percent, children)
