from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Phase(str, Enum):
    WORKING = "working"
    AWAY = "away"
    REMINDING = "reminding"


@dataclass(frozen=True)
class StateSnapshot:
    phase: Phase
    work_seconds: float
    away_seconds: float
    reminder_due: bool
    break_completed: bool
    remaining_break_seconds: float = 0.0


class SedentaryTracker:
    """与摄像头无关的久坐状态机。

    一个周期内同时累计：
    - work_seconds：实际检测到坐在座位区域的累计时间；短暂离开只暂停，不清零。
    - away_seconds：本周期已经获得的离座休息累计时间；回来后保留，不清零。

    当 away_seconds 达到 break_seconds 时，说明休息目的已经达到，整个周期重置。
    即使尚未达到久坐阈值，只要休息已经足量，也从新周期重新开始。

    正常运行没有“暂停”“延后提醒”等人工绕过入口。
    测试阶段保留 reset_cycle()，仅供强制休息界面的“测试关闭”保险使用。
    """

    def __init__(self, work_limit_seconds: float, break_seconds: float) -> None:
        self.work_limit_seconds = max(1.0, float(work_limit_seconds))
        self.break_seconds = max(1.0, float(break_seconds))
        self.work_seconds = 0.0
        self.away_seconds = 0.0
        self.reminder_active = False
        self.last_present = True

    def configure(self, work_limit_seconds: float, break_seconds: float) -> None:
        self.work_limit_seconds = max(1.0, float(work_limit_seconds))
        self.break_seconds = max(1.0, float(break_seconds))

    def reset_cycle(self, present: bool = True) -> None:
        """Reset the current work/break cycle.

        Used only by the temporary testing escape control while the detector is
        still being tuned. Production behavior should normally reset only after
        an effective break is completed.
        """
        self.work_seconds = 0.0
        self.away_seconds = 0.0
        self.reminder_active = False
        self.last_present = bool(present)

    @property
    def remaining_break_seconds(self) -> float:
        return max(0.0, self.break_seconds - self.away_seconds)

    def tick(self, present: bool, elapsed: float) -> StateSnapshot:
        elapsed = max(0.0, min(float(elapsed), 10.0))
        reminder_due = False
        break_completed = False
        self.last_present = bool(present)

        if present:
            self.work_seconds += elapsed
            if not self.reminder_active and self.work_seconds >= self.work_limit_seconds:
                self.reminder_active = True
                reminder_due = True
        else:
            self.away_seconds += elapsed
            if self.away_seconds >= self.break_seconds:
                break_completed = self.work_seconds > 0 or self.reminder_active
                self.work_seconds = 0.0
                self.away_seconds = 0.0
                self.reminder_active = False

        result = self.snapshot()
        return StateSnapshot(
            phase=result.phase,
            work_seconds=result.work_seconds,
            away_seconds=result.away_seconds,
            reminder_due=reminder_due,
            break_completed=break_completed,
            remaining_break_seconds=result.remaining_break_seconds,
        )

    def snapshot(self) -> StateSnapshot:
        if self.reminder_active:
            phase = Phase.REMINDING
        elif not self.last_present:
            phase = Phase.AWAY
        else:
            phase = Phase.WORKING
        return StateSnapshot(
            phase,
            self.work_seconds,
            self.away_seconds,
            False,
            False,
            self.remaining_break_seconds,
        )
