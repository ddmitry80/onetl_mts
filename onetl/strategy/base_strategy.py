from __future__ import annotations

import logging
from typing import Any

from onetl.connection.connection_helpers import LOG_INDENT

log = logging.getLogger(__name__)


class BaseStrategy:
    def __enter__(self):

        # hack to avoid circular imports
        from onetl.strategy.strategy_manager import StrategyManager

        log.debug(f"|{self.__class__.__name__}| Entered stack at level {StrategyManager.get_current_level()}")
        StrategyManager.push(self)
        log.info(f"|onETL| Using {self.__class__.__name__} as a strategy")
        log.info(f"|{self.__class__.__name__}| Using options:")

        for option, value in vars(self).items():
            log.info(" " * LOG_INDENT + f"{option} = {value}")

        self.enter_hook()
        return self

    def __exit__(self, exc_type, _exc_value, _traceback):
        from onetl.strategy.strategy_manager import StrategyManager

        log.debug(f"|{self.__class__.__name__}| Exiting stack at level {StrategyManager.get_current_level()-1}")
        strategy = StrategyManager.pop()

        strategy.exit_hook(failed=bool(exc_type))
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
