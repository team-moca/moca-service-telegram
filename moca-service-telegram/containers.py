"""Containers module."""

import logging
import sys
import coloredlogs
from . import dispatcher, session_storage
from .configurator import Configurator
from .mosquitto import Mosquitto
from .startup import Startup

from dependency_injector import containers, providers


class Container(containers.DeclarativeContainer):

    config = providers.Configuration()

    logging = providers.Resource(
        logging.basicConfig,
        stream=sys.stdout,
        level=config.log.level,
        format=config.log.format,
    )

    coloredlogs.install()

    sessions = providers.Singleton(
        session_storage.SessionStorage,
        config.telegram
    )

    configurator = providers.Singleton(
        Configurator,
        sessions
    )

    startup = providers.Singleton(
        Startup,
        sessions
    )

    mqtt = providers.Singleton(
        Mosquitto,
        configurator,
        sessions,
        config.mqtt
    )

    dispatcher = providers.Factory(
        dispatcher.Dispatcher,
        dispatchables=providers.List(
            startup,
            mqtt
        )
    )