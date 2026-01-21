@dataclass
class ArbitrageEvent:
    event_id: int
    symbol: str
    side: Literal["UP", "DOWN"]

    T0_cex_confirm: int      # ms
    T1_pm_first_touch: int | None
    T2_pm_reprice_start: int | None

    ΔT_touch: int | None
    ΔT_budget: int | None