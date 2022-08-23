from __future__ import annotations

import logging
from typing import Any

from onetl.impl import BaseModel
from onetl.log import log_with_indent

log = logging.getLogger(__name__)


class BaseStrategy(BaseModel):
    def __enter__(self):

        # hack to avoid circular imports
        from onetl.strategy.strategy_manager import StrategyManager

        log.debug(f"|{self.__class__.__name__}| Entered stack at level {StrategyManager.get_current_level()}")
        StrategyManager.push(self)

        self._log_parameters()
        self.enter_hook()
        return self

    def __exit__(self, exc_type, _exc_value, _traceback):
        from onetl.strategy.strategy_manager import StrategyManager

        log.debug(f"|{self.__class__.__name__}| Exiting stack at level {StrategyManager.get_current_level()-1}")
        strategy = StrategyManager.pop()

        failed = bool(exc_type)
        if failed:
            log.warning(f"|onETL| Exiting {self.__class__.__name__} because of {exc_type.__name__}")
        else:
            log.info(f"|onETL| Exiting {self.__class__.__name__}")

        strategy.exit_hook(failed=failed)
        return False

    @property  # noqa: WPS324
    def current_value(self) -> Any:
        return None  # noqa: WPS324

    @property  # noqa: WPS324
    def next_value(self) -> Any:
        return None  # noqa: WPS324

    def enter_hook(self) -> None:
        pass  # noqa: WPS420

    def exit_hook(self, failed: bool = False) -> None:
        pass  # noqa: WPS420

    def _log_parameters(self) -> None:
        log.info(f"|onETL| Using {self.__class__.__name__} as a strategy")
        parameters = self.dict(by_alias=True, exclude_none=True, exclude=self._log_exclude_fields())
        for attr, value in sorted(parameters.items()):
            log_with_indent(f"{attr} = {value!r}")

    @classmethod
    def _log_exclude_fields(cls) -> set[str]:
        return set()
