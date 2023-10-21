import logging
from threading import Thread

from strategies import EmaCrossOver


def init_logger(name):
    logger = logging.getLogger(name)
    # Краткий формат вывода лога (для удобства работы)
    FORMAT = logging.Formatter(fmt='%(asctime)s\t%(message)s', datefmt='%H:%M:%S')
    # Задаем глобальный уровень фильтрации логов
    logger.setLevel(logging.INFO)
    # Создаем обработчик потока debug сообщений
    handler = logging.StreamHandler()
    # Задаем уровень фильтрации логов для debug_handler
    handler.setLevel(logging.DEBUG)
    # Устанавливаем формат вывода сообщения
    handler.setFormatter(FORMAT)
    # Добавляем обработчик к логеру
    logger.addHandler(handler)


if __name__ == '__main__':
    # Запуск стратегии
    # Инициализируем логер
    init_logger('app')
    # Создание экземпляра класса стратегии
    ema_cross = EmaCrossOver(ticker='ETHUSDT',
                             interval='1m',
                             accuracy=150,
                             short_ema=6,
                             long_ema=12,
                             quantity=0.005,
                             future=True)
    # Стартуем стратегию
    Thread(target=ema_cross.run_forever).start()
