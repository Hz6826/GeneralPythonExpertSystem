# ./example/model.py
from dataclasses import dataclass
from collections.abc import Callable

Condition = Callable[["WorkingMemory"], bool]


@dataclass(frozen=True)
class Fact:
    name: str
    value: object = True

@dataclass
class Rule:
    name: str
    conditions: list[Condition]
    conclusion: Fact
    priority: int = 0

    def is_applicable(self, wm: "WorkingMemory") -> bool:
        return all(c(wm) for c in self.conditions)

    def apply(self, wm: "WorkingMemory") -> None:
        wm.add(self.conclusion)

    def __str__(self) -> str:
        return f"{self.name}({self.priority}): {self.conclusion}"

    def __repr__(self) -> str:
        def cond_name(c):
            return getattr(c, "__name__", None) or repr(c)
        return self.__str__() + "\n".join([f"{cond_name(c)}\n" for c in self.conditions])


class KnowledgeBase:
    def __init__(self) -> None:
        self.rules: list[Rule] = []

    def add_rule(self, rule: Rule) -> None:
        self.rules.append(rule)

    def remove_rule(self, rule: Rule) -> None:
        self.rules.remove(rule)

    def clear(self) -> None:
        self.rules.clear()

    def match(self, wm: WorkingMemory) -> list[Rule]:
        return [r for r in self.rules if r.is_applicable(wm)]


class WorkingMemory:
    def __init__(self) -> None:
        self.facts: set[Fact] = set()

    def add(self, fact: Fact) -> None:
        self.facts.add(fact)

    def remove(self, fact: Fact) -> None:
        self.facts.remove(fact)

    def contains(self, fact: Fact) -> bool:
        return fact in self.facts

    def clear(self) -> None:
        self.facts.clear()
