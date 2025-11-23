from typing import Any

class MainApp:
    """
    Entry point of the trading system.
    """

    def bootstrap(self) -> None:
        """
        Load config, create module singletons, start market client,
        start event loop, initialize strategies.
        """
        raise NotImplementedError

    def start(self) -> None:
        """Blocking call to start the system."""
        raise NotImplementedError
