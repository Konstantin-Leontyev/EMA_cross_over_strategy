import logging

import numpy

logger = logging.getLogger(__name__)


def ema(close_prices, period):
    # Создаем копию массива data с нулевыми значениями
    ema_values = numpy.zeros_like(close_prices)
    # Считаем стандартный сма для первого периода
    sma = numpy.mean(close_prices[:period])
    # Указываем первое значение в последнем элементе первого перебора
    ema_values[period - 1] = sma
    # Создаем условный множитель для округления (сглаживания) значения к более свежим данным (важность)
    multiplier = 2 / (period + 1)
    # Применяем цикл для перебора оставшегося массива и вычисления Экспоненциальной средней скользящей.
    for i in range(period, len(close_prices)):
        ema_values[i] = (close_prices[i] - ema_values[i - 1]) * multiplier + ema_values[i - 1]
    # Смысл тратить врем яна копирование всех элементов массива если нужен только один
    # return ema_values
    return ema_values[-1]

