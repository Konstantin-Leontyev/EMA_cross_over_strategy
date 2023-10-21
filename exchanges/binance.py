import hashlib
import hmac
import time
import requests
from requests import Response

from constants import BINANCE_BASE_FUTURES_URL, BINANCE_BASE_SPOT_URL


class Binance:
    """
    Класс Binance
    """
    def __init__(self, api_key: str = None, secret_key: str = None, is_future: bool = None):
        """
        Создает объект (клиент) класса :class:`Binance`

        .. Note:: Торговая площадка Binance имеет различные базовые URL для спотовой и фьючерсной торговли. Для
        создания клиента фьючерсного рынка необходимо передать параметр futures = True

        :param api_key: открытый ключ
        :param secret_key: приватный ключ
        :param is_future: флаг выбора URL для фьючерсного рынка
        :param secret_key: приватный ключ
        """
        self.exchange = 'Binance'
        self.api_key = api_key
        self.secret_key = secret_key
        self.is_future = is_future
        # Определение базовой ссылки
        if self.is_future:
            self.base_link = BINANCE_BASE_FUTURES_URL
        else:
            self.base_link = BINANCE_BASE_SPOT_URL
        # Формирование заголовка запроса
        self.headers = {'X-MBX-APIKEY': self.api_key}

    def sign_params(self, params: dict[str, any]) -> dict[str, any]:
        """
        Генерирует подпись для приватных запросов

        :return: :class:`str`
        """
        params['timestamp'] = int(time.time() * 1000)
        params_string = '&'.join([f"{key}={volume}" for key, volume in params.items()])
        sign = hmac.new(bytes(self.secret_key, 'utf-8'), params_string.encode('utf-8'), hashlib.sha256)
        params['signature'] = sign.hexdigest()
        return params

    def http_request(self, endpoint: str, method_type: str, params: dict[str, any] = None) -> Response:
        """
        Отправляет http запрос на сервер торговой площадки

        :param endpoint: url адрес запроса
        :param method_type: тип запроса `(GET`, `POST`, `DELETE)`
        :param params: тело запроса `(params)`

        :return: :class:`Response` (requests.models.Response)
        """
        # Отправка запроса
        if method_type == 'GET':
            return requests.get(url=self.base_link + endpoint, headers=self.headers, params=params)
        elif method_type == 'POST':
            return requests.post(url=self.base_link + endpoint, headers=self.headers, params=params)
        elif method_type == 'DELETE':
            return requests.delete(url=self.base_link + endpoint, headers=self.headers, params=params)
        elif method_type == 'PUT':
            return requests.put(url=self.base_link + endpoint, headers=self.headers, params=params)

    def get_candles(self, ticker: str, start_time: int = None, end_time: int = None,
                    interval: str = None, limit: int = None) -> list:
        """
        Возвращает список исторических свечей по торговой паре

        :param ticker: идентификатор торговой пары `(symbol)`
        :param start_time: начало запрашиваемого периода в формате UTC
        :param end_time: окончание запрашиваемого периода в формате UTC
        :param interval: интервал запрошенных свечей
        :param limit: количество свечей

        :return: :class:`list`
        """
        # Определение конечного адреса в зависимости от типа клиента
        if self.is_future:
            endpoint = '/fapi/v1/klines'
        else:
            endpoint = '/api/v3/klines'
        # Типа запроса
        method_type = 'GET'
        # Дополнительные параметры запроса
        params = {
            'symbol': ticker,
            'interval': interval,
        }
        # Расширение параметров запроса в зависимости от входящих значений
        if start_time:
            params['startTime'] = start_time
        if end_time:
            params['endTime'] = end_time
        if limit:
            params['limit'] = limit

        return self.http_request(endpoint=endpoint, method_type=method_type, params=params).json()

    def market_order(self, ticker: str, side: str, quantity: float) -> dict:
        """
        Выставляет рыночный ордер. Рыночный ордер исполняется мгновенно по лучшей текущей цене

        :param ticker: тикер
        :param side: направление сделки
        :param quantity: количество

        :return: :class:`dict`
        """
        if self.is_future:
            endpoint = '/fapi/v1/order'
        else:
            endpoint = '/api/v3/order'
        method_type = 'POST'
        params = {
            'symbol': ticker,
            'side': side,
            'type': 'MARKET',
            'quantity': quantity,
        }

        return self.http_request(method_type=method_type, endpoint=endpoint, params=self.sign_params(params)).json()

    def cancel_order(self, ticker: str, order_id: int) -> bool:
        """
        Отменяет ордер по указанному тикеру и идентификатору

        :param ticker: тикер
        :param order_id: идентификатор

        :return: :class:`bool`
        """
        if self.is_future:
            endpoint = '/fapi/v1/order'
        else:
            endpoint = '/api/v3/order'
        method_type = 'DELETE'
        params = {
            'symbol': ticker,
            'orderId': order_id,
        }
        # Отправка запроса
        response: Response = self.http_request(method_type=method_type, endpoint=endpoint,
                                               params=self.sign_params(params))
        # Обработка ответа
        if response.status_code == 200:
            return True
        else:
            return False

    def trailing_stop_order(self, ticker: str, side: str, quantity: float, trailing_delta: float, activation_price: float = None) -> dict:
        """
        Выставляет переменяющийся стоп

        :param ticker: тикер
        :param side: направление сделки
        :param quantity: количество
        :param activation_price: цена активации, если не передана то триггером выступает рыночная цена
        :param trailing_delta: размер отступа

        :return: :class:`dict`
        """
        method_type = 'POST'
        params = {
            'symbol': ticker,
            'side': side,
            'type': None,
            'timeInForce': 'GTC',
            'quantity': quantity,
        }
        if self.is_future:
            endpoint = '/fapi/v1/order'
            params['type'] = 'TRAILING_STOP_MARKET'
            if activation_price:
                params['activationPrice'] = activation_price
            params['callbackRate'] = trailing_delta
        else:
            endpoint = '/api/v3/order'
            params['type'] = 'STOP_LOSS_LIMIT'
            if activation_price:
                params['price'] = activation_price
                params['stopPrice'] = activation_price
            params['trailingDelta'] = trailing_delta * 100

        return self.http_request(method_type=method_type, endpoint=endpoint, params=self.sign_params(params)).json()

    def get_listen_key(self) -> dict:
        """
        Отправляет запрос на получение ключа потока пользовательских данных

        :return: :class:`dict`
        """
        method_type = 'POST'
        if self.is_future:
            endpoint = '/fapi/v1/listenKey'
        else:
            endpoint = 'api/v3/userDataStream'

        return self.http_request(method_type=method_type, endpoint=endpoint).json()

    def keep_alive_listen_key(self, listen_key: str) -> dict:
        """
        Отправляет запрос на продление ключа потока пользовательских данных

        :return: :class:`dict`
        """
        method_type = 'PUT'
        if self.is_future:
            endpoint = '/fapi/v1/listenKey'
        else:
            endpoint = 'api/v3/userDataStream'

        params = {'listenKey': listen_key}
        return self.http_request(method_type=method_type, endpoint=endpoint, params=params).json()

    def close_listen_key(self, listen_key: str) -> dict:
        """
        Отправляет запрос на отключение от потока пользовательских данных

        :return: :class:`dict`
        """
        method_type = 'DELETE'
        if self.is_future:
            endpoint = '/fapi/v1/listenKey'
        else:
            endpoint = 'api/v3/userDataStream'

        params = {'listenKey': listen_key}
        return self.http_request(method_type=method_type, endpoint=endpoint, params=params).json()



