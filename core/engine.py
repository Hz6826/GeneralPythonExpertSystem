# ./core/engine.py
import threading

from .model import Rule, KnowledgeBase, WorkingMemory, Fact
from typing import Iterator

class InferenceEngine:
    def __init__(self, kb=None, wm=None, max_iterations=1000):
        self.kb = kb if kb else KnowledgeBase()
        self.wm = wm if wm else WorkingMemory()
        self.max_iterations = max_iterations
        self._iterations = 0
        self._done = False
        self._stop_reason = None  # None | "no_rule" | "no_change" | "max_iter"
        self._fired: set[str] = set()  # 已经触发过的规则名
        # 用 RLock：run() 里会调 next(self)，而 __next__ 自己也拿锁，
        # 普通 Lock 会自锁死。
        self._lock = threading.RLock()
        self._running = False
        self._epoch = 0

    def __iter__(self) -> Iterator[Rule]:
        return self

    def __next__(self) -> Rule:
        with self._lock:
            if self._done or self._iterations >= self.max_iterations:
                # 如果之前已经设过原因就保留；否则说明是 max_iter 触发
                if self._stop_reason is None:
                    self._stop_reason = "max_iter"
                raise StopIteration

            matched = self.kb.match(self.wm)
            if not matched:
                self._done = True
                self._stop_reason = "no_rule"
                raise StopIteration

            # 选规则时优先选"还没触发过"的：同优先级时 max 会一直返回匹配列表里的
            # 第一条，导致同一条规则反复触发、后面的规则永远轮不到。
            rule = max(
                matched,
                key=lambda r: (0 if r.name in self._fired else 1, r.priority),
            )
            before = set(self.wm.facts)
            rule.apply(self.wm)
            self._iterations += 1

            # 同一条规则再次触发且依然没有新增事实 ⇒ 推理到达不动点。
            # 首次触发即使没有新增事实（结论已存在）也不算结束，
            # 否则排在它后面的规则没有机会触发。
            if self.wm.facts == before and rule.name in self._fired:
                self._done = True
                self._stop_reason = "no_change"

            self._fired.add(rule.name)
            return rule

    @property
    def stop_reason(self) -> str | None:
        return self._stop_reason

    @property
    def iterations(self) -> int:
        return self._iterations

    @property
    def reached_max_iterations(self) -> bool:
        return self._stop_reason == "max_iter"

    @property
    def running(self) -> bool:
        return self._running

    # step 作为别名:返回 Rule | None,给"单步调试"用
    def step(self) -> Rule | None:
        try:
            return next(self)
        except StopIteration:
            return None

    def run(self, epoch: int) -> None:
        while True:
            with self._lock:
                if not self._running or self._epoch != epoch:
                    break
            try:
                next(self)
            except StopIteration:
                break

    def run_in_background(self) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._epoch += 1
            my_epoch = self._epoch

        def _worker():
            try:
                self.run(my_epoch)
            finally:
                with self._lock:
                    if self._epoch == my_epoch:
                        self._running = False

        threading.Thread(target=_worker, daemon=True).start()
        return True

    def pause(self) -> bool:
        with self._lock:
            if not self._running:
                return False
            self._running = False
        return True

    def init(self):
        with self._lock:
            self._reset_locked()
            self.wm.clear()
            self.kb.clear()

    def reset(self):
        with self._lock:
            self._reset_locked()

    def _reset_locked(self):
        """假定调用方已持锁。"""
        self._iterations = 0
        self._done = False
        self._stop_reason = None
        self._fired.clear()

    def load_kb(self, kb, initial_facts=None):
        """替换知识库并复位推理状态（可选注入初始事实）。"""
        with self._lock:
            self.kb = kb
            self.wm.clear()
            if initial_facts:
                for f in initial_facts:
                    self.wm.add(f)
            self._reset_locked()

    def get_facts(self) -> list[Fact]:
        """返回当前工作内存中的事实（按 name 排序，便于前端稳定显示）。"""
        with self._lock:
            return sorted(self.wm.facts, key=lambda f: f.name)

    def add_fact(self, fact: Fact) -> None:
        """加入事实；同名（name 相同）的旧事实会被覆盖，避免同 name 多值。"""
        with self._lock:
            for old in [f for f in self.wm.facts if f.name == fact.name]:
                self.wm.remove(old)
            self.wm.add(fact)
            self._reopen_locked()

    def remove_fact(self, name: str) -> bool:
        """按 name 删除事实，返回是否删到过。"""
        with self._lock:
            matched = [f for f in self.wm.facts if f.name == name]
            for f in matched:
                self.wm.remove(f)
            if matched:
                self._reopen_locked()
            return bool(matched)

    def clear_facts(self) -> None:
        with self._lock:
            if self.wm.facts:
                self.wm.clear()
                self._reopen_locked()

    def _reopen_locked(self) -> None:
        """事实变动后，如果引擎因 no_rule/no_change 停机，重新允许继续推理。

        因 max_iter 停机时不动：iteration 上限还在，重新打开也是立刻再停。
        """
        if self._done and self._stop_reason != "max_iter":
            self._done = False
            self._stop_reason = None
