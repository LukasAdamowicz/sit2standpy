"""
Wavelet based methods of detecting postural transitions

Lukas Adamowicz
June 2019
"""
from numpy import mean, diff, arange, logical_and, sum as npsum, std, timedelta64, where, insert, append, array_split, \
    concatenate
from scipy.signal import find_peaks
from pandas import to_datetime
import pywt
from multiprocessing import cpu_count, Pool

from pysit2stand.utility import AccFilter
from pysit2stand import detectors


class AutoSit2Stand:
    """
    Automatically run the sit-2-stand analysis on a sample of data. Data windowing will be done automatically if
    necessary based on the provided parameters

    Parameters
    ----------
    acceleration : numpy.ndarray
        (N, 3) array of accelerations measured by a lumbar mounted accelerometer. Units of m/s^2.
    timestamps : numpy.ndarray
        (N, ) array of timestamps.
    time_units : str, optional
        Units of the timestamps. Options are those for converting to pandas.datetimes, ('ns', 'us', 'ms', etc), or
        'datetime' if the timestamps are already pandas.datetime64. Default is 'us' (microseconds).
    window : bool, optional
        Window the provided data into parts of days. Default is True
    hours : tuple, optional
        Tuple of the hours to use to window the data. The indices define the start and stop time of the window during
        the day, ex ('00:00', '24:00') is the whole day. Default is ('08:00', '20:00').
    parallel : bool, optional
        Use parallel processing. Ignored if `window` is False. Default is False.
    parallel_cpu : {'max', int}, optional
        Number of CPUs to use for parallel processing. Ignored if parallel is False. 'max' uses the maximum number
        of CPUs available on the machine, or provide a number less than the maximum to use. Default is 'max'.

    Sit to Stand Detection Parameters
    ---------------------------------
    continuous_wavelet : str, optional
        Continuous wavelet to use for signal deconstruction. Default is 'gaus1'. CWT coefficients will be summed
        in frequency bands that will be used for detecting approximate STS locations.
    peak_pwr_band : {array_like, int, float}, optional
        Frequency band in which to sum the CWT coefficients. Either an array_like of length 2, with the lower and
        upper limits, or a number, which will be taken as the upper limit, and the lower limit will be set to 0.
        Default is [0, 0.5].
    peak_pwr_par : {None, dict}, optional
        Extra parameters (key-word arguments) to pass to scipy.signal.find_peaks when finding peaks in the
        summed CWT coefficient power band data. Default is None, which will use the default parameters, unless
        std_height is True.
    std_height : bool, optional
        Use the standard deviation of the power for peak finding. Default is True.

    Attributes
    ----------
    s2s : Sit2Stand
        The Sit2Stand object framework for detecting sit-to-stand transitions
    days : list
        List of tuples of the indices corresponding to the different days as determined by hours and if data has been
        windowed
    abs_time : pandas.DatetimeIndex
        DatetimeIndex, converted from the provided timestamps
    """
    def __init__(self, acceleration, timestamps, time_units='us', window=True, hours=('08:00', '20:00'), parallel=False,
                 parallel_cpu='max', continuous_wavelet='gaus1', peak_pwr_band=[0, 0.5], peak_pwr_par=None,
                 std_height=True, verbose=True):
        self.verbose = verbose

        if parallel_cpu == 'max':
            self.n_cpu = cpu_count()
        elif parallel_cpu > cpu_count():
            self.n_cpu = cpu_count()
        else:
            self.n_cpu = parallel_cpu

        if not window:
            self.parallel = False
        else:
            self.parallel = parallel

        if time_units is not 'datetime':
            if self.verbose:
                print('Converting timestamps to datetimes...\n')

            if self.parallel:
                pool = Pool(self.n_cpu)
                times = array_split(timestamps, self.n_cpu)

                other_args = ('raise', False, False, None, True, None, True, time_units)
                result = pool.starmap(to_datetime, [(t, ) + other_args for t in times])
                self.abs_time = result[0].append(result[1:])
                pool.close()
            else:
                self.abs_time = to_datetime(timestamps, unit=time_units)
        else:
            self.abs_time = timestamps

        if window:
            if self.verbose:
                print('Setting up windows...\n')
            days_inds = self.abs_time.indexer_between_time(hours[0], hours[1])

            day_ends = days_inds[where(diff(days_inds) > 1)[0]]
            day_starts = days_inds[where(diff(days_inds) > 1)[0] + 1]

            if day_ends[0] < day_starts[0]:
                day_starts = insert(day_starts, 0, 0)
            if day_starts[-1] > day_ends[-1]:
                day_ends = append(day_ends, self.abs_time.size - 1)

            self.days = []
            for start, end in zip(day_starts, day_ends):
                self.days.append(range(start, end))
        else:
            self.days = [range(0, self.abs_time.size)]

        self.accel = acceleration

        # initialize the sit2stand detection object
        if parallel:
            self.s2s = [Sit2Stand(continuous_wavelet=continuous_wavelet, peak_pwr_band=peak_pwr_band,
                             peak_pwr_par=peak_pwr_par, std_height=std_height) for i in range(len(self.days))]
        else:
            self.s2s = Sit2Stand(continuous_wavelet=continuous_wavelet, peak_pwr_band=peak_pwr_band,
                                 peak_pwr_par=peak_pwr_par, std_height=std_height)
        if self.verbose:
            print('Initialization Done!\n')

    def run(self, acc_filter_kwargs=None, detector='stillness', detector_kwargs=None):
        """
        Run the sit to stand detection

        Parameters
        ----------
        acc_filter_kwargs : {None, dict}, optional
            AccFilter key-word arguments. See Notes for default values. See `pysit2stand.AccFilter` for description
            of the parameters
        detector : {'stillness', 'displacement'}
            Detector method to use. Default is 'stillness'
        detector_kwargs : {None, dict}, optional
            Detector method key-word arguments. See Notes for the default values, and `pysit2stand.detectors` for the
            parameters of the chosen detector.

        Returns
        -------
        sts : dict
            Dictionary of pysit2stand.Transition objects containing information about a individual sit-to-stand
            transition. Keys for the dictionary are string timestamps of the start of the transition.

        Attributes
        ----------
        acc_filter : AccFilter
            The AccFilter object
        self.detector : {detectors.Stillness, detectors.Displacement}
            The detector object as determined by the choice in `detector`

        Notes
        -----
        AccFilter default parameters
            - reconstruction_method='moving average'
            - lowpass_order=4
            - lowpass_cutoff=5
            - window=0.25,
            - discrete_wavelet='dmey'
            - extension_mode='constant'
            - reconstruction_level=1
        Detector methods default parameters
            - gravity=9.81
            - thresholds=None
            - gravity_pass_ord=4
            - gravity_pass_cut=0.8
            - long_still=0.5,
            - moving_window=0.3
            - duration_factor=10
            - displacement_factor=0.75
            - lmax_kwargs=None
            - lmin_kwargs=None
            - trans_quant=TransitionQuantifier()
        """
        if self.verbose:
            print('Setting up filters and detector...\n')

        self.acc_filter = AccFilter(**acc_filter_kwargs)

        if detector == 'stillness':
            self.detector = detectors.Stillness(**detector_kwargs)
        elif detector == 'displacement':
            self.detector = detectors.Displacement(**detector_kwargs)
        else:
            raise ValueError(f"detector '{detector}' not recognized.")

        if self.parallel:
            if self.verbose:
                print('Processing in parallel...\n')
            pool = Pool(min(self.n_cpu, len(self.days)))

            tmp = [pool.apply_async(self.s2s[i].fit, args=(self.accel[day], self.abs_time[day], self.detector,
                                                           self.acc_filter)) for i, day in enumerate(self.days)]
            results = [p.get() for p in tmp]

            pool.close()

        else:
            if self.verbose:
                print('Processing...\n')
            results = self.s2s.fit(self.accel, self.abs_time, self.detector, self.acc_filter)

        if self.verbose:
            print('Done!\n')
        return results


class Sit2Stand:
    """
    Wavelet based detection of sit-to-stand transitions

    Parameters
    ----------
    continuous_wavelet : str, optional
        Continuous wavelet to use for signal deconstruction. Default is 'gaus1'. CWT coefficients will be summed
        in frequency bands that will be used for detecting approximate STS locations.
    peak_pwr_band : {array_like, int, float}, optional
        Frequency band in which to sum the CWT coefficients. Either an array_like of length 2, with the lower and
        upper limits, or a number, which will be taken as the upper limit, and the lower limit will be set to 0.
        Default is [0, 0.5].
    peak_pwr_par : {None, dict}, optional
        Extra parameters (key-word arguments) to pass to scipy.signal.find_peaks when finding peaks in the
        summed CWT coefficient power band data. Default is None, which will use the default parameters, unless
        std_height is True.
    std_height : bool, optional
        Use the standard deviation of the power for peak finding. Default is True.
    """

    def __init__(self, continuous_wavelet='gaus1', peak_pwr_band=[0, 0.5], peak_pwr_par=None, std_height=True):
        self.cwave = continuous_wavelet  # TODO add checks this is a valid wavelet

        if isinstance(peak_pwr_band, (int, float)):
            self.pk_pwr_start = 0
            self.pk_pwr_stop = peak_pwr_band
        else:
            self.pk_pwr_start = peak_pwr_band[0]
            self.pk_pwr_stop = peak_pwr_band[1]

        if peak_pwr_par is None:
            self.pk_pwr_par = {'height': 90}
        else:
            self.pk_pwr_par = peak_pwr_par

        self.std_height = std_height
        if self.std_height:
            if 'height' in self.pk_pwr_par:
                del self.pk_pwr_par['height']

    def fit(self, accel, time, detector, acc_filter, fs=None):
        """
        Fit the data and determine sit-to-stand transitions start and stop times.

        First, the data is filtered using the acc_filter.apply(). After which, the Continuous Wavelet Transform is
        taken of the reconstructed data. The CWT coefficients are summed in the specified power band, and peaks are
        found. Filtered data, power peaks, and CWT data are passed to the detector.apply() method, which detects the
        sit-to-stand transitions.

        Parameters
        ----------
        accel : numpy.ndarray
            (N, 3) array of raw accelerations measured by a lumbar sensor.
        time : pandas.DatetimeIndex
            (N, ) array of pandas.DatetimeIndex corresponding with the acceleration data.
        detector : pysit2stand.detectors
            Initialized detector objects for detecting the sit-to-stand transisions. Must have an apply method. If
            creating a new object for this detection, see pysit2stand.detector.Displacement for the required arguments.
        acc_filter : pysit2stand.AccFilter
            Acceleration filter object, used to filter and reconstruct the magnitude of the acceleration. Must have
            an apply() method (eg acc_filter.apply()) that takes the raw acceleration, and sampling frequency only
            as arguments.
        fs : {None, float}, optional
            Sampling frequency. If none, calculated from the time. Default is None.

        Returns
        -------
        sts : dict
            Dictionary of pysit2stand.Transition objects containing information about a individual sit-to-stand
            transition. Keys for the dictionary are string timestamps of the start of the transition.
        """
        # calculate the sampling time and frequency
        if fs is None:
            dt = mean(diff(time)) / timedelta64(1, 's')  # convert to seconds
            fs = 1 / dt
        else:
            dt = 1 / fs

        # filter the raw acceleration using the AccFilter object
        self.macc_f, self.macc_r = acc_filter.apply(accel, fs)

        # compute the continuous wavelet transform on the reconstructed acceleration data
        self.coefs, self.freqs = pywt.cwt(self.macc_r, arange(1, 65), self.cwave, sampling_period=dt)

        # sum the CWT coefficients over the set of frequencies specified in the peak power band
        f_mask = logical_and(self.freqs <= self.pk_pwr_stop, self.freqs >= self.pk_pwr_start)
        self.power = npsum(self.coefs[f_mask, :], axis=0)

        # find the peaks in the power data
        if self.std_height:
            self.pwr_pks, _ = find_peaks(self.power, height=std(self.power, ddof=1), **self.pk_pwr_par)
        else:
            self.pwr_pks, _ = find_peaks(self.power, **self.pk_pwr_par)

        # use the detector object to fully detect the sit-to-stand transitions
        sts = detector.apply(accel, self.macc_f, self.macc_r, time, dt, self.pwr_pks, self.coefs, self.freqs)

        return sts


