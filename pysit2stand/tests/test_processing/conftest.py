from pytest import fixture
from importlib import resources
from numpy import loadtxt, random
from pandas import date_range, to_datetime

# -------------------------------------------------------------------------------------------------
#                               RAW DATA
# -------------------------------------------------------------------------------------------------
@fixture
def raw_accel():
    # pull sample data
    with resources.path('pysit2stand.data', 'sample.csv') as file_path:
        acc = loadtxt(file_path, dtype=float, delimiter=',', usecols=(1, 2, 3))

    return acc


@fixture
def time():
    # pull sample time data
    with resources.path('pysit2stand.data', 'sample.csv') as file_path:
        time = loadtxt(file_path, dtype=float, delimiter=',', usecols=0)

    return time


# -------------------------------------------------------------------------------------------------
#                               ROLLING MEAN FILTERED DATA
# -------------------------------------------------------------------------------------------------
@fixture
def filt_accel_rm():
    # pull the filtered data
    with resources.path('pysit2stand.data', '.filter_results_rm.csv') as file_path:
        filt_accel = loadtxt(file_path, dtype=float, delimiter=',', usecols=0)

    return filt_accel


@fixture
def rm_accel_rm():
    # pull the rolling mean acceleration
    with resources.path('pysit2stand.data', '.filter_results_rm.csv') as file_path:
        rm_accel = loadtxt(file_path, dtype=float, delimiter=',', usecols=1)

    return rm_accel


@fixture
def power_rm():
    # pull the power measure
    with resources.path('pysit2stand.data', '.filter_results_rm.csv') as file_path:
        power = loadtxt(file_path, dtype=float, delimiter=',', usecols=2)

    return power


@fixture
def power_peaks_rm():
    # pull the power peaks
    with resources.path('pysit2stand.data', '.filter_results_rm.csv') as file_path:
        power_peaks = loadtxt(file_path, dtype=int, delimiter=',', usecols=3)

    power_peaks = power_peaks[power_peaks != -1]  # remove filler values

    return power_peaks


# -------------------------------------------------------------------------------------------------
#                               DWT RECONSTRUCTED FILTERED DATA
# -------------------------------------------------------------------------------------------------
@fixture
def filt_accel_dwt():
    # pull the filtered data
    with resources.path('pysit2stand.data', '.filter_results_dwt.csv') as file_path:
        filt_accel = loadtxt(file_path, dtype=float, delimiter=',', usecols=0)

    return filt_accel


@fixture
def rec_accel_dwt():
    # pull the rolling mean acceleration
    with resources.path('pysit2stand.data', '.filter_results_dwt.csv') as file_path:
        rm_accel = loadtxt(file_path, dtype=float, delimiter=',', usecols=1)

    return rm_accel


@fixture
def power_dwt():
    # pull the power measure
    with resources.path('pysit2stand.data', '.filter_results_dwt.csv') as file_path:
        power = loadtxt(file_path, dtype=float, delimiter=',', usecols=2)

    return power


@fixture
def power_peaks_dwt():
    # pull the power peaks
    with resources.path('pysit2stand.data', '.filter_results_dwt.csv') as file_path:
        power_peaks = loadtxt(file_path, dtype=int, delimiter=',', usecols=3)

    power_peaks = power_peaks[power_peaks != -1]  # remove filler values

    return power_peaks


# -------------------------------------------------------------------------------------------------
#                               GENERATED TIMESTAMP DATA
# -------------------------------------------------------------------------------------------------
@fixture
def overnight_time_accel():
    # generate some time that spans overnight, to testing windowing
    ts = date_range(start='2019-10-10 16:00', end='2019-10-11 12:00', freq='1H').astype(int)
    # generate random acceleration values with the same shape
    acc = random.rand(ts.size)

    return ts, acc


@fixture
def windowed_timestamps():
    ts = to_datetime(['2019-10-10 16:00:00', '2019-10-10 17:00:00', '2019-10-10 18:00:00', '2019-10-10 19:00:00',
                      '2019-10-10 20:00:00', '2019-10-11 08:00:00', '2019-10-11 09:00:00', '2019-10-11 10:00:00',
                      '2019-10-11 11:00:00', '2019-10-11 12:00:00'], format='%Y-%m-%d %H:%M:%S')
    return ts


@fixture
def timestamps_time_accel():
    ts = date_range(start='2019-10-10 16:00', end='2019-10-10 16:02', freq='0.05S')
    time = ts.astype(int)
    acc = random.rand(ts.size)

    return ts, time, acc
