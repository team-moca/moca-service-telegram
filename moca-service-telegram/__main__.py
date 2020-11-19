"""Main module."""


from dependency_injector.wiring import inject, Provide

import sys

from .dispatcher import Dispatcher
from .containers import Container

@inject
def main(dispatcher: Dispatcher = Provide[Container.dispatcher]) -> None:
    dispatcher.run()


if __name__ == "__main__":
    container = Container()
    container.config.from_yaml("config.yml")
    container.init_resources()
    container.wire(modules=[sys.modules[__name__]])

    main()
