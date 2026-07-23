from __future__ import annotations

from types import SimpleNamespace

from tucam_control.gas_analyzer import GasConfig, GasResult
from tucam_control.ui.main_window import MainWindow


class _SignalRecorder:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def emit(self, message: str) -> None:
        self.messages.append(message)


def _result(concentration: float) -> GasResult:
    return GasResult(
        name="halong",
        position=179,
        found_col=179,
        peak_height=1.0,
        peak_area=1.0,
        coefficient=1.0,
        component=1.0,
        concentration=concentration,
    )


def test_smoothed_alarm_stops_when_display_value_reaches_threshold() -> None:
    stopped: list[str] = []
    capture_states: list[bool] = []
    window = SimpleNamespace(
        _settings={"gas_emergency_stop": True},
        _camera=SimpleNamespace(is_capturing=True),
        _gas_alarm_stopped=False,
        _pending_frame=object(),
        _analyzer=SimpleNamespace(
            gases=[GasConfig("halong", 179, alarm_concentration=10.0)]
        ),
        _stop_continuous_capture=stopped.append,
        _acq_tab=SimpleNamespace(set_capturing_state=capture_states.append),
        status_changed=_SignalRecorder(),
    )

    triggered = MainWindow._check_smoothed_gas_alarm(
        window,
        [[_result(0.101)]],
        ["行 890-930"],
        "time",
    )

    assert triggered is True
    assert stopped == ["smoothed gas concentration alarm"]
    assert capture_states == [False]
    assert window._pending_frame is None
    assert window._gas_alarm_stopped is True


def test_smoothed_alarm_ignores_disabled_and_batch_modes() -> None:
    for enabled, mode in ((False, "time"), (True, "index")):
        window = SimpleNamespace(
            _settings={"gas_emergency_stop": enabled},
            _camera=SimpleNamespace(is_capturing=True),
            _gas_alarm_stopped=False,
            _pending_frame=None,
        )

        assert MainWindow._check_smoothed_gas_alarm(
            window,
            [[_result(0.50)]],
            ["行 890-930"],
            mode,
        ) is False
