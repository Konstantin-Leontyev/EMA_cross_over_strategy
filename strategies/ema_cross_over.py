import json
import logging
from threading import Thread, Timer
import time
import traceback

import numpy
from websocket import WebSocketApp

from exchanges import Binance
from indicators import ema
from keys import API_KEY, SECRET_KEY

logger = logging.getLogger('app.strategies.ema_cross_over')


class EmaCrossOver(WebSocketApp):
    def __init__(self, ticker: str, interval: str, accuracy: int, short_ema: int, long_ema: int, quantity: float,
                 future: bool = False):
        """
        Стратегия основанная на пересечении экспоненциальных скользящих средних.
        Период скользящих, объем позиции и тайм фрейм задается пользователем.
        Стоп выставляется автоматически на уровень ближайшего последнего максимума/минимума,
        с учетом 2% проскальзывания.

        Для изменения уровня проскальзывания передайте соответсвующий параметр в функцию, размещающую стоп ордер

        :param ticker: тикер торговой пары
        :param interval: тайм фрейм
        :param accuracy: точность (количество свечей используемых при расчете EMA)
        :param short_ema: период короткой скользящей
        :param long_ema: период длинной скользящей
        :param quantity: объем позиции
        """
        self.ticker: str = ticker
        # Клиент
        self.client = Binance(api_key=API_KEY, secret_key=SECRET_KEY, is_future=future)
        # Ключ потока пользовательских данных
        self.listen_key = self.get_listen_key()
        logger.info(self.listen_key)
        # Имена потоков
        self.candles_stream = f"{self.ticker.lower()}@kline_{interval}"
        stream_names: list[str] = [self.listen_key, self.candles_stream]
        # Создание строки подключения
        if future:
            url = f"wss://fstream-auth.binance.com/stream?streams={'/'.join(name for name in stream_names)}" \
                  f"&listenKey={self.listen_key}"
        else:
            url = f"wss://stream.binance.com:9443/stream?streams={self.listen_key}" \
                  f"{'/'.join(name for name in stream_names)}"
        super().__init__(url=url,
                         on_open=self.on_open,
                         on_message=self.on_message,
                         on_error=self.on_error,
                         on_close=self.on_close,
                         on_ping=self.on_ping)
        self.interval = interval
        self.accuracy: int = accuracy
        self.short_ema: int = short_ema
        self.long_ema: int = long_ema
        self.quantity: float = quantity
        # Динамически обновляемые списки
        self.close_prices = None
        self.high_prices = None
        self.low_prices = None
        self.real_time_close_prices = None
        self.previous_shor_list = []
        self.previous_long_list = []
        # Предыдущие значения скользящих для работы в режиме реального времени
        self.previous_short_value = None
        self.previous_long_value = None
        # Информация об открытой позиции
        self.position: dict[str, any] = {'side': None, 'orderId': None}
        # Идентификатор стопа
        self.stop_order_id = None
        # Стартовый запрос архива свечей
        self.get_start_data()
        self.run_forever = self.run_forever(reconnect=10)

    def __str__(self):
        return f"Стратегия: Пересечение скользящих средних\n" \
               f"Биржа: {self.client.exchange}\n" \
               f"Url: {self.url}\n" \
               f"Тикер: {self.ticker}\n" \
               f"Рабочий объем: {self.quantity}\n" \
               f"Тайм фрейм: {self.interval}\n" \
               f"Точность: {self.quantity}\n" \
               f"Короткая EMA: {self.short_ema}\n" \
               f"Длинная EMA: {self.long_ema}\n" \
               f"Архив цен закрытия: {self.close_prices}"

    def on_open(self, ws):
        logger.info('Бот запущен')
        self.keep_alive_listen_key()

    def on_error(self, ws, error):
        logger.info(traceback.format_exc())

    def on_close(self, ws, close_status_code, close_message):
        self.close_listen_key()
        logger.info('Бот остановлен')

    def on_ping(self, ws, message):
        logger.info('Получен пинг')

    def on_message(self, ws, message):
        message = json.loads(message)
        # Фильтр потока пользовательских данных (обновление ордеров)
        if message['stream'] == self.listen_key and message['data']['e'] == 'ORDER_TRADE_UPDATE':
            # Если информация об отмене стоп ордера
            if message['data']['o']['i'] == self.stop_order_id and message['data']['o']['X'] == 'CANCELED':
                logger.info(f"Стоп ордер {self.stop_order_id} отменён")
                self.stop_order_id = None
            # Если информация об исполнении стоп ордера
            if message['data']['o']['ot'] == "TRAILING_STOP_MARKET" and message['data']['o']['X'] == 'FILLED':
                self.stop_order_id = None
                self.position['side'] = None
                self.position['orderId'] = None
                logger.info(f"Сработал стоп:"
                            f"\n{json.dumps(message['data']['o'], indent=2)}"
                            f"\nДанные о позиции сброшены")
            # Если информация об ордере входа в позицию
            if message['data']['o']['i'] == self.position['orderId'] and message['data']['o']['X'] == 'FILLED':
                logger.info(f"Информация о {'покупке' if self.position['side'] == 'BUY' else 'продаже'}:"
                            f"\n{json.dumps(message['data']['o'], indent=2)}")
        # Фильтр потока свечей (обновление ордеров)
        if message['stream'] == self.candles_stream:
            if message['data']['k']['x']:
                Thread(target=self.edit_data_arrays(data=message['data']['k']))
            Thread(target=self.real_time_close_price(real_time_close_price=float(message['data']['k']['c'])))

    def get_start_data(self):
        # Получение списка свечей
        candles = self.client.get_candles(ticker=self.ticker, interval=self.interval, limit=self.accuracy)
        if (time.time() * 1000) < candles[-1][6]:
            candles.pop()
        numpy_candles = numpy.array(candles)
        # Заполнение списка цен закрытия
        self.close_prices = numpy_candles[:, 4].astype(float)
        # Заполнение списка вершин
        self.high_prices = numpy_candles[:, 2].astype(float)
        # Заполнение списка низов
        self.low_prices = numpy_candles[:, 3].astype(float)
        # Заполнение списков последних значений
        # Для этого сначала получаем последние значения
        self.previous_short_value = ema(close_prices=self.close_prices, period=self.short_ema)
        self.previous_long_value = ema(close_prices=self.close_prices, period=self.long_ema)
        # Используются три последних значения, чтобы избежать входа в точке ложного (кратковременного) пересечения
        # Заполняется на старте, что бы не вышло ошибок при первой проверке пустого списка
        # Так как они будут равны ни одно из условий проверки не выполнится
        for i in range(120):
            self.previous_shor_list.append(self.previous_short_value)
            self.previous_long_list.append(self.previous_long_value)

    def edit_data_arrays(self, data: dict):
        # Обеспечивая сдвиг данных, храним только последние accuracy свечей
        # Удаление последнего элемента в списках закрытия, вершин и минимумов
        self.close_prices = numpy.delete(self.close_prices, 0)
        self.high_prices = numpy.delete(self.high_prices, 0)
        self.low_prices = numpy.delete(self.low_prices, 0)
        # Обновление данных (добавление в конец нового значения) в списках цен закрытия, вершин и минимумов
        self.close_prices = numpy.append(self.close_prices, float(data['c']))
        self.high_prices = numpy.append(self.high_prices, float(data['h']))
        self.low_prices = numpy.append(self.low_prices, float(data['l']))
        if not self.position['side']:
            logger.info('Нет сигнала')
        else:
            logger.info(f"Открыта {'длинная' if self.position['side'] == 'BUY' else 'короткая'} позиция")

    def real_time_close_price(self, real_time_close_price: float):
        # Изменение списка цен закрытия в режиме реального времени
        self.real_time_close_prices = numpy.append(self.close_prices, real_time_close_price)
        self.check_signal()

    def get_last_low(self):
        array = numpy.flip(self.low_prices)
        last_low = array[0]
        for index in range(self.accuracy):
            if array[index] > last_low:
                return last_low
            else:
                last_low = array[index]

    def get_last_high(self):
        array = numpy.flip(self.high_prices)
        last_high = array[0]
        for index in range(self.accuracy):
            if array[index] < last_high:
                return last_high
            else:
                last_high = array[index]

    def open_position(self, side: str):
        # Если нет позиции
        if not self.position['side']:
            # Входим в рынок
            quantity = self.quantity
        else:
            # Встаем на разворот
            quantity = self.quantity * 2
            logger.info('Вход на разворот')
            # Отменяем лимитный стоп предыдущей позиции
            self.client.cancel_order(ticker=self.ticker, order_id=self.stop_order_id)

        while True:
            order = self.client.market_order(ticker=self.ticker, side=side, quantity=quantity)
            # Проверка на случай возврата ошибки при выставлении ордера
            if order.get('orderId'):
                self.position['side'] = side
                self.position['orderId'] = order['orderId']
                break

    def set_stop(self, side: str):
        # Стоп выставляется в цикле, как защита от возможного отказа сервера, до тех пор пока ответ не будет получен
        while self.stop_order_id is None:
            stop_order = self.client.trailing_stop_order(ticker=self.ticker,
                                                         side=side,
                                                         quantity=self.quantity,
                                                         trailing_delta=0.1)
            # Проверка на случай возврата ошибки при выставлении ордера
            if stop_order.get('orderId'):
                self.stop_order_id = stop_order['orderId']
                logger.info(f"Выставлен стоп ордер: {self.stop_order_id}")

    def is_down(self) -> bool:
        # Проверка, чтобы три последних динамических значения были ниже
        return all(a < b for a, b in zip(self.previous_shor_list, self.previous_long_list))

    def is_up(self) -> bool:
        # Проверка, чтобы три последних динамических значения были выше
        return all(a > b for a, b in zip(self.previous_shor_list, self.previous_long_list))

    def check_signal(self):
        # Получаем последнее значения скользящих в режиме реального времени
        last_short_value = ema(close_prices=self.real_time_close_prices, period=self.short_ema)
        # logger.debug(last_short_value)
        last_long_value = ema(close_prices=self.real_time_close_prices, period=self.long_ema)
        # logger.debug(last_long_value)

        # Фильтруем действия в зависимости наличия открытой позиции
        # Если позиции нет или позиция на продажу
        if self.position['side'] in ('SELL', None):
            # Проверяем есть ли сигнал на покупку
            if self.is_down() and last_short_value > last_long_value:
                logger.info('Сигнал на покупку')
                self.open_position(side='BUY')
                self.set_stop(side='SELL')
        # Если позиции нет или позиция на покупку
        if self.position['side'] in ('BUY', None):
            # Проверяем есть ли сигнал на продажу
            if self.is_up() and last_short_value < last_long_value:
                logger.info('Сигнал на продажу')
                self.open_position(side='SELL')
                self.set_stop(side='BUY')

        # Удаление последних значений в списках значений последних скользящих реального времени
        del self.previous_shor_list[0]
        del self.previous_long_list[0]
        # Добавление в конец последних значений скользящих реального времени
        self.previous_shor_list.append(last_short_value)
        self.previous_long_list.append(last_long_value)

    def get_listen_key(self) -> str:
        response = self.client.get_listen_key()
        if response['listenKey']:
            return response['listenKey']
        else:
            logger.info('Ошибка получения ключа потока пользовательских данных')
            self.close()

    def keep_alive_listen_key(self):
        logger.info('Отправка запроса на продление подключения к потоку пользовательских данных')
        while True:
            response = self.client.keep_alive_listen_key(self.listen_key)
            # Обработка ответа
            if response == {}:
                logger.info('Продление подключения к потоку пользовательских данных подтверждено')
                break
            else:
                logger.info('Ошибка продления подключения к потоку пользовательских данных')
        Timer(interval=1800, function=self.keep_alive_listen_key).start()

    def close_listen_key(self):
        logger.info('Отправка уведомления об отключении от потока пользовательских данных')
        response = self.client.close_listen_key(self.listen_key)
        if response == {}:
            logger.info('Отключение от потока пользовательских данных подтверждено')
        else:
            logger.info('Ошибка отключения от потока пользовательских данных')
