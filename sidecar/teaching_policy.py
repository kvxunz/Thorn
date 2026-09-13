from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TeachingPolicy:
    max_depth: int | None = None

    def __post_init__(self):
        if self.max_depth is not None and self.max_depth < 0:
            raise ValueError("teaching depth must be nonnegative")

    def project(self, chunks, depth=0):
        output = []
        for chunk in chunks:
            projected = dict(chunk)
            children = chunk.get("children")
            projected["children"] = (
                self.project(children, depth + 1)
                if children and (self.max_depth is None or depth < self.max_depth)
                else None
            )
            output.append(projected)
        return output
