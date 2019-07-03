"""
Methods for sit to stand transition detection, using previously processed data

Lukas Adamowicz
June 2019
Pfizer
"""
from numpy import around, gradient, abs as npabs, where, diff, sum as npsum, isclose, append, arange, array, sign, \
    median
from numpy.linalg import norm
from scipy.integrate import cumtrapz
from scipy.signal import find_peaks, butter, filtfilt, detrend
from matplotlib.lines import Line2D

from pysit2stand import utility as u_
from pysit2stand.common import Transition


__all__ = ['Similarity', 'Stillness', 'Displacement']


# some common methods
def _get_still(mag_acc_f, dt, window, gravity, thresholds):
    """
    Stillness determination of acceleration magnitude data

    Parameters
    ----------
    mag_acc_f : numpy.ndarray
        (N, 3) array of filtered acceleration data.
    dt : float
        Sampling time difference, in seconds.
    window : float
        Moving statistics window length, in seconds.
    gravity : float
        Gravitational acceleration, as measured by the sensor during static sitting or standing.
    thresholds : dict
        Dictionary of the 4 thresholds to be used - acceleration and jerk moving averages and standard deviations.

    Returns
    -------
    acc_still : numpy.ndarray
        (N, ) boolean array indicating stillness
    starts : numpy.ndarray
        (Q, ) array of where stillness ends, where by necessity has to follow: Q < N / 2
    stops : numpy.ndarray
        (P, ) array of where stillness ends, where by necessity has to follow: P < N / 2
    """
    # calculate the sample window from the time window
    n_window = int(around(window / dt))
    # compute the acceleration moving standard deviation
    am_avg, am_std, _ = u_.mov_stats(mag_acc_f, n_window)
    # compute the jerk
    jerk = gradient(mag_acc_f, dt, edge_order=2)
    # compute the jerk moving average and standard deviation
    jm_avg, jm_std, _ = u_.mov_stats(jerk, n_window)

    # create masks from the moving statistics of acceleration and jerk
    am_avg_mask = npabs(am_avg - gravity) < thresholds['accel moving avg']
    am_std_mask = am_std < thresholds['accel moving std']
    jm_avg_mask = npabs(jm_avg) < thresholds['jerk moving avg']
    jm_std_mask = jm_std < thresholds['jerk moving std']

    acc_still = am_avg_mask & am_std_mask & jm_avg_mask & jm_std_mask
    starts = where(diff(acc_still.astype(int)) == 1)[0]
    stops = where(diff(acc_still.astype(int)) == -1)[0]

    if acc_still[0]:
        starts = append(0, starts)
    if acc_still[-1]:
        stops = append(stops, len(acc_still) - 1)

    # TODO Could consider adding all the masks together and filtering, then taking values above a threshold

    return acc_still, starts, stops


def _integrate_acc(acc, dt, still_at_end):
    """
    Double integrate acceleration along 1 axis (ie 1D) to get velocity and position

    Parameters
    ----------
    acc : numpy.ndarray
        (N, ) array of acceleration values to integrate
    dt : float
        Time difference between samples of acceleration in seconds.
    still_at_end : bool
        Whether or not the acceleration ends with a still period. Determines how drift is mitigated.

    Returns
    -------
    vel : numpy.ndarray
        (N, ) array of velocities
    pos : numpy.ndarray
        (N, ) array of positions
    """
    x = arange(acc.size)

    # integrate and drift mitigate
    if not still_at_end:
        # fc = butter(1, [2 * 0.1 * dt, 2 * 5 * dt], btype='band')
        # vel = cumtrapz(filtfilt(fc[0], fc[1], acc), dx=dt, initial=0)
        vel = detrend(cumtrapz(acc, dx=dt, initial=0))
        if npabs(vel[0]) > 0.05:  # if too far away from zero
            vel -= vel[0]  # reset the beginning back to 0, the integration always starts with stillness
    else:
        vel_dr = cumtrapz(acc, dx=dt, initial=0)
        vel = vel_dr - (((vel_dr[-1] - vel_dr[0]) / (x[-1] - x[0])) * x)  # no intercept

    # integrate the velocity to get position
    pos = cumtrapz(vel, dx=dt, initial=0)

    return vel, pos


class Similarity:
    def __init__(self, gravity_value=9.81, low_f_band=[0, 0.5], high_f_band=[0, 3], similarity_atol=0,
                 similarity_rtol=0.15, tr_pk_diff=0.5, start_pos='fixed', acc_peak_params=None, acc_trough_params=None):
        """
        Sit-to-stand (STS) detection based on similarity of summed coefficients of the Continuous Wavelet Transform
        in different power bands

        Parameters
        ----------
        gravity_value : float, optional
            Value of gravitational acceleration of the sensor during still standing or sitting. Default is 9.81m/s^2.
        low_f_band : {array_like, float, int}, optional
            Low frequency limits for the low freq. power band, obtained by summing CWT coefficients in this band of
            frequencies. Can either be a length 2 array_like (min, max), or a number, which will be interpreted as the
            maximum value, with 0 Hz as the minimum. Default is [0, 0.5].
        high_f_band : {array_like, float, int}, optional
            High frequency limits for the high freq. power band, obtained by summing CWT coefficients in this band of
            frequencies. Can either be a length 2 array_like (min, max), or a number, which will be interpreted as the
            maximum value, with 0 Hz as the minimum. Default is [0, 3].
        similarity_atol : {float, int}, optional
            Absolute tolerance for determining similarity between the high and low frequency power bands. Default is 0
        similarity_rtol : {float, int}, optional
            Relative tolerance for dtermining similarity between the high and low frequency power bands. Default is 0.15
        tr_pk_diff : float, optional
            Minimum difference in acceleration magnitude between troughs and peaks that is used in determining the end
            time for the STS transitions. Default is 0.5 m/s^2.
        start_pos : {'fixed', 'variable'}, optional
            How the start of STS transitions is determined. Either a fixed location, or can be variable among several
            possible locations, and the best location is chosen. Default is 'fixed'
        acc_peak_params : {None, dict}, optional
            Additional parameters (key-word arguments) to be passed to scipy.signal.find_peaks for finding peaks in the
            acceleration magnitude. Default is None, for which the find_peaks defaults will be used.
        acc_trough_params : {None, dict}, optional
            Additional parameters (key-word arguments) to be passed to scipy.signal.find_peaks for finding troughs
            (local minima) in the acceleration magnitude. Default is None, for which the find_peaks defaults will be
            used.
        """
        self.gravity = gravity_value

        if isinstance(low_f_band, (float, int)):
            self.low_f = [0, low_f_band]
        else:
            self.low_f = low_f_band  # TODO add check for length
        if isinstance(high_f_band, (float, int)):
            self.high_f = [0, high_f_band]
        else:
            self.high_f = high_f_band

        self.sim_atol = similarity_atol
        self.sim_rtol = similarity_rtol

        self.tp_diff = tr_pk_diff

        if start_pos == 'fixed' or start_pos == 'variable':
            self.start_pos = start_pos
        else:
            raise ValueError('start_pos must be either "fixed" or "variable".')

        if acc_peak_params is None:
            self.acc_pk_kw = {}
        else:
            self.acc_pk_kw = acc_peak_params
        if acc_trough_params is None:
            self.acc_tr_kw = {}
        else:
            self.acc_tr_kw = acc_trough_params

    def apply(self, raw_acc, mag_acc, mag_acc_r, time, dt, power_peaks, cwt_coefs, cwt_freqs):
        """
        Apply the stillness-based STS detection to the given data

        Parameters
        ----------
        mag_acc : numpy.ndarray
            (N, 3) array of filtered acceleration magnitude.
        mag_acc_r : numpy.ndarray
            (N, 3) array of reconstructed acceleration magnitude.
        time : numpy.ndarray
            (N, ) array of time-stamps (in seconds) corresponding with the acceleration
        dt : float
            Sampling time difference
        power_peaks : numpy.ndarray
            Locations of the peaks in the CWT power data.
        cwt_coefs : numpy.ndarray
            (M, N) array of coefficients for the CWT, where M is the number of scales used in the computation.
        cwt_freqs : numpy.ndarray
            (M, ) array of frequencies from the CWT

        Returns
        -------
        sts : list
            List of tuples of the form (STS start, STS end) for the detected STS transitions in the provided data.
        extra : dict
            Dictionary of extra returns, mostly used for plotting. Keyword 'plot' can contain an array of indices to
            be plotted from the acceleration data
        """
        # compute the sum of the scales in certain frequency bands
        low_mask = (cwt_freqs > self.low_f[0]) & (cwt_freqs < self.low_f[1])
        high_mask = (cwt_freqs > self.high_f[0]) & (cwt_freqs < self.high_f[1])

        # compute the powers in those bands
        low_pwr = npsum(cwt_coefs[low_mask, :], axis=0)
        high_pwr = npsum(cwt_coefs[high_mask, :], axis=0)

        # compute the indices where the two power measures are close in value
        similar = isclose(high_pwr, low_pwr, atol=self.sim_atol, rtol=self.sim_rtol)

        # find troughs and peaks in the filtered signal
        acc_pks, _ = find_peaks(mag_acc, **self.acc_pk_kw)
        acc_trs, _ = find_peaks(-mag_acc_r, **self.acc_tr_kw)

        # find the stops in similarity
        stops = where(diff(similar.astype(int)) == -1)[0]
        sim_starts = where(diff(similar.astype(int)) == 1)[0]

        # iterate over the detected power peaks and determine STS locations
        sts = {}
        for ppk in power_peaks:
            # find the first trough after the power peak
            try:
                next_tr = acc_trs[acc_trs > ppk][0]  # get the next trough
            except IndexError:
                continue
            # find the first peak after the found trough, though ensure that there is enough difference that it is
            # not just artefact
            try:
                next_pk = acc_pks[acc_pks > next_tr][0]
                if mag_acc[next_pk] - mag_acc[next_tr] < self.tp_diff:
                    next_pk = acc_pks[acc_pks > next_tr][1]
            except IndexError:
                continue
            # make sure ppk to stop isn't too long
            if (time[next_pk] - time[ppk]).total_seconds() > 2:
                continue
            # find the second previous stop of similarity in the power bands
            try:
                prev2_stop = stops[stops < ppk][-2]
                if self.start_pos == 'variable':
                    prev_start = sim_starts[sim_starts > prev2_stop][0]
                    if npabs(mag_acc[prev2_stop] - self.gravity) < npabs(mag_acc[prev_start] - self.gravity):
                        start = prev2_stop
                        alt_start = prev_start
                    else:
                        start = prev_start
                        alt_start = None
                else:
                    start = prev2_stop
                    alt_start = None
            except IndexError:
                continue
            # ensure that there is no overlap with previously detected transitions
            if len(sts) > 0:
                if (time[start] - sts[list(sts.keys())[-1]][1]).total_seconds() < 0.5:  # min time between transitions
                    if alt_start is not None:
                        if (time[alt_start] - sts[list(sts.keys())[-1]][1]) < 0.5:
                            continue
                        else:
                            start = alt_start
            # sts.append((time[start], time[next_pk]))
            a_max, a_min = mag_acc_r[start:next_pk].max(), mag_acc_r[start:next_pk].min()
            sts[f'{time[start]}'] = Transition((time[start], time[next_pk]), max_acceleration=a_max,
                                               min_acceleration=a_min)

        return sts, {'plot': similar}


class Stillness:
    def __init__(self, gravity=9.81, thresholds=None, gravity_pass_ord=4, gravity_pass_cut=0.8, long_still=0.5,
                 moving_window=0.3, duration_factor=3, displacement_factor=0.75, lmax_kwargs=None,
                 lmin_kwargs=None):
        """
        Method for detecting sit-to-stand transitions based on requiring stillness before a transition, and the
        vertical displacement of a lumbar accelerometer for ensuring a transition.

        Parameters
        ----------
        gravity : float, optional
            Value of gravitational acceleration measured by the accelerometer when still. Default is 9.81 m/s^2.
        thresholds : {None, dict}, optional
            Either None, for the default, or a dictionary of thresholds to change. See
            PosiStillDetector.default_thresholds for a dictionary of the thresholds and their default values. Default
            is None, which uses the default values.
        gravity_pass_ord : int, optional
            Low-pass filter order for estimating the direction of gravity by low-pass filtering the raw acceleration
            data. Default is 4.
        gravity_pass_cut : float, optional
            Low-pass filter frequency cutoff for estimating thd direction of gravity. Default is 0.8Hz.
        long_still : float, optional
            Length of time of stillness for it to be qualified as a long period of stillness. Used to determing
            integration limits when available. Default is 0.5s.
        moving_window : float, optional
            Length of the moving window for calculating the moving statistics for determining stillness.
            Default is 0.3s.
        duration_factor : float, optional
            The factor for the maximum difference between the duration before and after the generalized location of
            the sit to stand. Lower factors result in more equal time before and after the detection. Default
            is 3.
        displacement_factor : float, optional
            Factor multiplied by the median of the vertical displacements to determine the threshold for checking if a
            transition is a partial transition or a full transition. Default is 0.75
        lmax_kwargs : {None, dict}, optional
            Additional key-word arguments for finding local maxima in the acceleration signal. Default is None,
            for no specified arguments. See scipy.signal.find_peaks for possible arguments.
        lmin_kwargs : {None, dict}, optional
            Additional key-word arguments for finding local minima in the acceleration signal. Default is None,
            for no specified arguments. See scipy.signal.find_peaks for the possible arguments.
        """
        # set the default thresholds
        self.default_thresholds = {'stand displacement': 0.15,
                                   'transition velocity': 0.2,
                                   'accel moving avg': 0.25,
                                   'accel moving std': 0.5,
                                   'jerk moving avg': 3,
                                   'jerk moving std': 5}
        # assign attributes
        self.grav = gravity

        self.thresh = {i: self.default_thresholds[i] for i in self.default_thresholds.keys()}
        if thresholds is not None:
            for key in thresholds.keys():
                if key in self.thresh:
                    self.thresh[key] = thresholds[key]

        self.grav_ord = gravity_pass_ord
        self.grav_cut = gravity_pass_cut

        self.long_still = long_still
        self.mov_window = moving_window

        self.dur_factor = duration_factor
        self.disp_factor = displacement_factor

        if lmin_kwargs is None:
            self.lmin_kw = {}
        else:
            self.lmin_kw = lmin_kwargs
        if lmax_kwargs is None:
            self.lmax_kw = {}
        else:
            self.lmax_kw = lmax_kwargs

    def apply(self, raw_acc, mag_acc, mag_acc_r, time, dt, power_peaks, cwt_coefs, cwt_freqs):
        # find stillness
        acc_still, still_starts, still_stops = _get_still(mag_acc, dt, self.mov_window, self.grav, self.thresh)
        # starts and stops of long still periods
        # still_dt = (still_stops - still_starts) * dt  # durations of stillness, in seconds
        # lstill_starts = still_starts[still_dt > self.long_still]
        # lstill_stops = still_stops[still_dt > self.long_still]

        # find the local minima and maxima in the acceleration signals. Use the reconstructed acceleration for
        # local minima, as this avoids some possible artefacts in the signal
        acc_lmax, _ = find_peaks(mag_acc, **self.lmax_kw)
        acc_lmin, _ = find_peaks(-mag_acc_r, **self.lmin_kw)

        # compute an estimate of the direction of gravity, assumed to be the vertical direction
        gfc = butter(self.grav_ord, 2 * self.grav_cut * dt, btype='low')
        vert = filtfilt(gfc[0], gfc[1], raw_acc, axis=0, padlen=None)
        vert /= norm(vert, axis=1, keepdims=True)  # make into unit vectors

        # get an estimate of the vertical acceleration
        v_acc = npsum(vert * raw_acc, axis=1)

        # iterate over the power peaks
        sts = {}
        pos_lines = []

        prev_int_start = -1
        prev_int_stop = -1

        for ppk in power_peaks:
            try:  # look for any preceding end of any stillness
                end_still = still_stops[still_stops < ppk][-1]
                if (time[ppk] - time[end_still]).total_seconds() > 2:  # ensure not too far back TODO parameter?
                    raise IndexError
            except IndexError:
                continue
            try:  # look for the following local min -> local max pattern
                n_lmin = acc_lmin[acc_lmin > ppk][0]
                n_lmax = acc_lmax[acc_lmax > n_lmin][0]
                if (time[n_lmax] - time[ppk]).total_seconds() > 2:  # ensure not too far ahead TODO parameter?
                    raise IndexError
            except IndexError:
                continue
            try:  # look for a still period for integration
                start_still = still_starts[still_starts > ppk][0]
                if start_still < n_lmax:
                    raise IndexError
                elif (time[start_still] - time[ppk]).total_seconds() < 30:  # can integrate for a while
                    still_at_end = True
                else:
                    raise IndexError
            except IndexError:
                start_still = n_lmax
                still_at_end = True

            # INTEGRATE the signal between the start and stop points
            if end_still < prev_int_start or start_still > prev_int_stop:
                v_vel, v_pos = _integrate_acc(v_acc[end_still:start_still] - self.grav, dt, still_at_end)
                # plotting the position
                pos_lines.append(Line2D(time[end_still:start_still], v_pos, color='C5', linewidth=1.5))

                # save the used integration limits
                prev_int_start = end_still
                prev_int_stop = start_still

                # find the zero crossings
                pos_zc = where(diff(sign(v_vel)) > 0)[0]
                neg_zc = where(diff(sign(v_vel)) < 0)[0]

                if neg_zc.size == 0:
                    if v_vel[-1] < 1e-2:
                        neg_zc = array([v_pos.size - 1])
            # ensure that the vertical velocity indicates that it is a peak as well
            if v_vel[ppk - prev_int_start] < self.thresh['transition velocity']:
                continue
            try:  # previous and next zero crossings
                p_pzc = pos_zc[pos_zc + prev_int_start < ppk][-1]
                n_nzc = neg_zc[neg_zc + prev_int_start < ppk][0]
            except IndexError:
                continue

            # quality checks
            if (time[ppk] - time[end_still]).total_seconds() > self.dur_factor * (time[n_lmax]
                                                                                  - time[ppk]).total_seconds():
                continue
            if npabs((time[p_pzc + end_still] - time[end_still]).total_seconds()) > 0.35:  # TODO parameter?
                continue
            if (v_pos[n_nzc] - v_pos[p_pzc]) < self.thresh['stand displacement']:
                continue
            # STS creation
            if len(sts) > 0:
                if (time[end_still] - sts[list(sts.keys())[-1]].end_time).total_seconds() > 0.5:  # prevent overlap
                    v_disp = v_pos[n_lmax - end_still] - v_pos[0]
                    v_max, v_min = v_vel[0:n_lmax - end_still].max(), v_vel[0:n_lmax - end_still].min()
                    a_max, a_min = mag_acc_r[end_still:n_lmax].max(), mag_acc_r[end_still:n_lmax].min()
                    sts[f'{time[end_still]}'] = Transition((time[end_still], time[n_lmax]),
                                                           v_displacement=v_disp, max_v_velocity=v_max,
                                                           min_v_velocity=v_min, max_acceleration=a_max,
                                                           min_acceleration=a_min)
            else:
                v_disp = v_pos[n_lmax - end_still] - v_pos[0]
                v_max, v_min = v_vel[0:n_lmax - end_still].max(), v_vel[0:n_lmax - end_still].min()
                a_max, a_min = mag_acc_r[end_still:n_lmax].max(), mag_acc_r[end_still:n_lmax].min()
                sts[f'{time[end_still]}'] = Transition((time[end_still], time[n_lmax]),
                                                       v_displacement=v_disp, max_v_velocity=v_max,
                                                       min_v_velocity=v_min, max_acceleration=a_max,
                                                       min_acceleration=a_min)

        # check to ensure no partial transitions
        vd = [sts[i].v_displacement for i in sts]
        vd_high_diff = array(vd) < self.disp_factor * median(vd)
        for elem in array(list(sts.keys()))[vd_high_diff]:
            del sts[elem]

        # plot the still periods
        l1 = Line2D(time[acc_still], mag_acc[acc_still], color='k', marker='.', ls='')

        return sts, {'pos lines': pos_lines, 'lines': [l1]}


class Displacement:
    def __init__(self, gravity=9.81, thresholds=None, gravity_pass_ord=4, gravity_pass_cut=0.8, long_still=0.5,
                 moving_window=0.3, duration_factor=10, displacement_factor=0.75, lmax_kwargs=None,
                 lmin_kwargs=None):
        """
        Method for detecting sit-to-stand transitions based on requiring stillness before a transition, and the
        vertical displacement of a lumbar accelerometer for ensuring a transition.

        Parameters
        ----------
        gravity : float, optional
            Value of gravitational acceleration measured by the accelerometer when still. Default is 9.81 m/s^2.
        thresholds : {None, dict}, optional
            Either None, for the default, or a dictionary of thresholds to change. See Notes. Default
            is None, which uses the default values.
        gravity_pass_ord : int, optional
            Low-pass filter order for estimating the direction of gravity by low-pass filtering the raw acceleration
            data. Default is 4.
        gravity_pass_cut : float, optional
            Low-pass filter frequency cutoff for estimating thd direction of gravity. Default is 0.8Hz.
        long_still : float, optional
            Length of time of stillness for it to be qualified as a long period of stillness. Used to determing
            integration limits when available. Default is 0.5s.
        moving_window : float, optional
            Length of the moving window for calculating the moving statistics for determining stillness.
            Default is 0.3s.
        duration_factor : float, optional
            The factor for the maximum difference between the duration before and after the generalized location of
            the sit to stand. Lower factors result in more equal time before and after the detection. Default
            is 3.
        displacement_factor : float, optional
            Factor multiplied by the median of the vertical displacements to determine the threshold for checking if a
            transition is a partial transition or a full transition. Default is 0.75
        lmax_kwargs : {None, dict}, optional
            Additional key-word arguments for finding local maxima in the acceleration signal. Default is None,
            for no specified arguments. See scipy.signal.find_peaks for possible arguments.
        lmin_kwargs : {None, dict}, optional
            Additional key-word arguments for finding local minima in the acceleration signal. Default is None,
            which specifies a maximum value of 9.5m/s^2 for local minima. See scipy.signal.find_peaks for the
            possible arguments.

        Notes
        -----
        Default thresholds:
            stand displacement: 0.125
            transition velocity: 0.2
            accel moving avg: 0.2
            accel moving std: 0.1
            jerk moving avg: 2.5
            jerk moving std: 3
        """
        # set the default thresholds
        self.default_thresholds = {'stand displacement': 0.125,
                                   'transition velocity': 0.2,
                                   'accel moving avg': 0.2,
                                   'accel moving std': 0.1,
                                   'jerk moving avg': 2.5,
                                   'jerk moving std': 3}
        # assign attributes
        self.grav = gravity

        self.thresh = {i: self.default_thresholds[i] for i in self.default_thresholds.keys()}
        if thresholds is not None:
            for key in thresholds.keys():
                if key in self.thresh:
                    self.thresh[key] = thresholds[key]

        self.grav_ord = gravity_pass_ord
        self.grav_cut = gravity_pass_cut

        self.long_still = long_still
        self.mov_window = moving_window

        self.dur_factor = duration_factor
        self.disp_factor = displacement_factor

        if lmin_kwargs is None:
            self.lmin_kw = {'height': -9.5}
        else:
            self.lmin_kw = lmin_kwargs
        if lmax_kwargs is None:
            self.lmax_kw = {}
        else:
            self.lmax_kw = lmax_kwargs

    def apply(self, raw_acc, mag_acc, mag_acc_r, time, dt, power_peaks, cwt_coefs, cwt_freqs):
        # find stillness
        acc_still, still_starts, still_stops = _get_still(mag_acc, dt, self.mov_window, self.grav, self.thresh)
        # starts and stops of long still periods
        still_dt = (still_stops - still_starts) * dt  # durations of stillness, in seconds
        lstill_starts = still_starts[still_dt > self.long_still]
        lstill_stops = still_stops[still_dt > self.long_still]

        # find the local minima and maxima in the acceleration signals. Use the reconstructed acceleration for
        # local minima, as this avoids some possible artefacts in the signal
        acc_lmax, _ = find_peaks(mag_acc, **self.lmax_kw)
        acc_lmin, _ = find_peaks(-mag_acc_r, **self.lmin_kw)

        # compute an estimate of the direction of gravity, assumed to be the vertical direction
        gfc = butter(self.grav_ord, 2 * self.grav_cut * dt, btype='low')
        vert = filtfilt(gfc[0], gfc[1], raw_acc, axis=0, padlen=None)
        vert /= norm(vert, axis=1, keepdims=True)  # make into unit vectors

        # get an estimate of the vertical acceleration
        v_acc = npsum(vert * raw_acc, axis=1)

        # iterate over the power peaks
        sts = {}
        pos_lines = []

        prev_int_start = -1
        prev_int_stop = -1

        for ppk in power_peaks:
            try:  # look for the preceding end of long stillness
                end_still = lstill_stops[lstill_stops < ppk][-1]
                if (time[ppk] - time[end_still]).total_seconds() > 30:  # don't want to integrate for too long
                    raise IndexError
            except IndexError:
                end_still = int(ppk - (2.5 / dt))  # try to use a set time before the peak
            try:  # look for the next start of long stillness
                start_still = lstill_starts[lstill_starts > ppk][0]
                if (time[start_still] - time[ppk]).total_seconds() < 30:
                    still_at_end = True
                else:
                    raise IndexError
            except IndexError:
                start_still = int(ppk + (5 / dt))  # try to use a set time after the peak
                still_at_end = False

            # INTEGRATE between the determined indices
            if end_still < prev_int_start or start_still > prev_int_stop:
                v_vel, v_pos = _integrate_acc(v_acc[end_still:start_still] - self.grav, dt, still_at_end)
                # plotting of the position
                pos_lines.append(Line2D(time[end_still:start_still], v_pos, color='C5', linewidth=1.5))

                # set used limits
                prev_int_start = end_still
                prev_int_stop = start_still

                # zero crossings
                pos_zc = append(0, where(diff(sign(v_vel)) > 0)[0]) + end_still
                neg_zc = append(where(diff(sign(v_vel)) < 0)[0], v_vel.size - 1) + end_still

            # make sure the velocity is high enough to indicate a peak
            if v_vel[ppk - prev_int_start] < self.thresh['transition velocity']:
                continue
            try:  # look for the previous positive zero crossing as the start of the transition
                sts_start = pos_zc[pos_zc < ppk][-1]
                p_still = still_stops[still_stops < ppk][-1]
                # possibly use the end of stillness if it is close enough to the ZC
                if -0.5 < (dt * (p_still - sts_start)) < 0.7:
                    sts_start = p_still
                # if (time[ppk] - time[sts_start]).total_seconds() > 2:  # TODO parameter?
                #     raise IndexError
            except IndexError:
                continue
            try:  # find the end of the transition
                # n_lmin = acc_lmin[acc_lmin > ppk][0]
                # n_lmax = acc_lmax[acc_lmax > n_lmin][0]
                sts_end = neg_zc[neg_zc > ppk][0]
                # if (time[sts_end] - time[ppk]).total_seconds() > 2:  # TODO parameter
                #     raise IndexError
            except IndexError:
                continue

            # quatity checks
            if (time[sts_end] - time[sts_start]).total_seconds() > 4.5:
                continue
            if (time[ppk] - time[sts_start]).total_seconds() > self.dur_factor * (time[sts_end]
                                                                                  - time[ppk]).total_seconds():
                continue
            # test_ind = sts_end - end_still if (sts_end - end_still) < v_pos.size else -1
            t_start_i = sts_start - prev_int_start  # integrated value start index
            t_end_i = sts_end - prev_int_start  # integrated value end index
            if (v_pos[t_end_i] - v_pos[t_start_i]) < self.thresh['stand displacement']:
                continue

            # sts assignment
            if len(sts) > 0:
                if (time[sts_start] - sts[list(sts.keys())[-1]].end_time).total_seconds() > 0.4:  # no overlap TODO param?
                    v_disp = v_pos[t_end_i] - v_pos[t_start_i]
                    v_max, v_min = v_vel[t_start_i:t_end_i].max(), v_vel[t_start_i:t_end_i].min()
                    a_max, a_min = mag_acc_r[t_start_i:t_end_i].max(), mag_acc_r[t_start_i:t_end_i].min()
                    sts[f'{time[sts_start]}'] = Transition(times=(time[sts_start], time[sts_end]),
                                                           v_displacement=v_disp, max_v_velocity=v_max,
                                                           min_v_velocity=v_min, max_acceleration=a_max,
                                                           min_acceleration=a_min)
            else:
                v_disp = v_pos[t_end_i] - v_pos[t_start_i]
                v_max, v_min = v_vel[t_start_i:t_end_i].max(), v_vel[t_start_i:t_end_i].min()
                a_max, a_min = mag_acc_r[t_start_i:t_end_i].max(), mag_acc_r[t_start_i:t_end_i].min()
                sts[f'{time[sts_start]}'] = Transition(times=(time[sts_start], time[sts_end]),
                                                       v_displacement=v_disp, max_v_velocity=v_max,
                                                       min_v_velocity=v_min, max_acceleration=a_max,
                                                       min_acceleration=a_min)

        # check to ensure no partial transitions
        vd = [sts[i].v_displacement for i in sts]
        vd_high_diff = array(vd) < self.disp_factor * median(vd)
        for elem in array(list(sts.keys()))[vd_high_diff]:
            del sts[elem]

        # plot the still periods
        l1 = Line2D(time[acc_still], mag_acc[acc_still], color='k', marker='.', ls='')

        return sts, {'pos lines': pos_lines, 'lines': [l1]}


class OldStaticMethods:
    @staticmethod
    def _get_position(acc, dt, still_at_end):
        """
        Double integrate acceleration along 1 axis (ie 1D) to get velocity and position

        Parameters
        ----------
        acc : numpy.ndarray
            (N, ) array of acceleration values to integrate
        still_at_end : bool
            Whether or not the acceleration ends with a still period. Determines how drift is mitigated.

        Returns
        -------
        vel : numpy.ndarray
            (N, ) array of velocities
        pos : numpy.ndarray
            (N, ) array of positions
        """
        x = arange(acc.size)

        # integrate and drift mitigate
        if not still_at_end:
            # fc = butter(1, [2 * 0.1 * dt, 2 * 5 * dt], btype='band')
            # vel = cumtrapz(filtfilt(fc[0], fc[1], acc), dx=dt, initial=0)
            vel = detrend(cumtrapz(acc, dx=dt, initial=0))
            if npabs(vel[0]) > 0.05:  # if too far away from zero
                vel -= vel[0]  # reset the beginning back to 0, the integration always starts with stillness
        else:
            vel_dr = cumtrapz(acc, dx=dt, initial=0)
            vel = vel_dr - (((vel_dr[-1] - vel_dr[0]) / (x[-1] - x[0])) * x)  # no intercept

        # integrate the velocity to get position
        pos = cumtrapz(vel, dx=dt, initial=0)

        return vel, pos

    @staticmethod
    def _stillness(mag_acc_f, dt, window, gravity, thresholds):
        """
        Stillness determination of acceleration magnitude data

        Parameters
        ----------
        mag_acc_f : numpy.ndarray
            (N, 3) array of filtered acceleration data.
        dt : float
            Sampling time difference, in seconds.
        window : float
            Moving statistics window length, in seconds.
        gravity : float
            Gravitational acceleration, as measured by the sensor during static sitting or standing.
        thresholds : dict
            Dictionary of the 4 thresholds to be used - acceleration and jerk moving averages and standard deviations.

        Returns
        -------
        acc_still : numpy.ndarray
            (N, ) boolean array indicating stillness
        starts : numpy.ndarray
            (Q, ) array of where stillness ends, where by necessity has to follow: Q < N / 2
        stops : numpy.ndarray
            (P, ) array of where stillness ends, where by necessity has to follow: P < N / 2
        """
        # calculate the sample window from the time window
        n_window = int(around(window / dt))
        # compute the acceleration moving standard deviation
        am_avg, am_std, _ = u_.mov_stats(mag_acc_f, n_window)
        # compute the jerk
        jerk = gradient(mag_acc_f, dt, edge_order=2)
        # compute the jerk moving average and standard deviation
        jm_avg, jm_std, _ = u_.mov_stats(jerk, n_window)

        # create masks from the moving statistics of acceleration and jerk
        am_avg_mask = npabs(am_avg - gravity) < thresholds['accel moving avg']
        am_std_mask = am_std < thresholds['accel moving std']
        jm_avg_mask = npabs(jm_avg) < thresholds['jerk moving avg']
        jm_std_mask = jm_std < thresholds['jerk moving std']

        acc_still = am_avg_mask & am_std_mask & jm_avg_mask & jm_std_mask
        starts = where(diff(acc_still.astype(int)) == 1)[0]
        stops = where(diff(acc_still.astype(int)) == -1)[0]

        if acc_still[0]:
            starts = append(0, starts)
        if acc_still[-1]:
            stops = append(stops, len(acc_still) - 1)

        # TODO Could consider adding all the masks together and filtering, then taking values above a threshold

        return acc_still, starts, stops


class Position:
    def __init__(self, gravity=9.81, heigh_thresh=0.15, vel_thresh=0.1, grav_pass_ord=4, grav_pass_cut=0.8,
                 still_window=0.5, mov_window=0.3, mov_avg_thresh=0.25, mov_std_thresh=0.5, jerk_mov_avg_thresh=3,
                 jerk_mov_std_thresh=5):
        self.grav = gravity

        self.height = heigh_thresh

        self.vel_thresh = vel_thresh

        self.grav_ord = grav_pass_ord
        self.grav_cut = grav_pass_cut
        self.still_wind = still_window

        self.mov_wind = mov_window

        self.avg_thresh = mov_avg_thresh
        self.std_thresh = mov_std_thresh
        self.j_avg_thresh = jerk_mov_avg_thresh
        self.j_std_thresh = jerk_mov_std_thresh

    def apply(self, raw_acc, mag_acc, mag_acc_r, time, dt, power_peaks, cwt_coefs, cwt_freqs):
        # get the estimate of gravity
        b, a = butter(self.grav_ord, 2 * self.grav_cut * dt)
        grav_est = filtfilt(b, a, raw_acc, axis=0)
        grav_est /= norm(grav_est, axis=1, keepdims=True)  # normalize the gravity estimate
        # compute the vertical acceleration
        v_acc = npsum(grav_est * raw_acc, axis=1)

        # find still periods in the data
        acc_still, stops = Position._stillness(mag_acc, dt, self.mov_wind, self.grav, self.avg_thresh,
                                               self.std_thresh, self.j_avg_thresh, self.j_std_thresh)
        if acc_still[-1]:
            stops = append(stops, acc_still.size)
        starts = where(diff(acc_still.astype(int)) == 1)[0]
        if acc_still[0]:
            starts = append(0, starts)

        # determine where the stillness durations are over the threshold
        n_still = self.still_wind / dt  # window size in samples
        durs = stops - starts  # length in samples

        long_start = starts[durs > n_still]
        long_stop = stops[durs > n_still]

        sts = []
        # save the last integrated velocity
        pint_start, pint_stop = 0, 0
        # plotting
        pos_lines = []
        # iterate over the power peaks
        for ppk in power_peaks:
            # find the mid-points of the previous and next long still sections
            try:
                int_start = int(long_stop[long_stop < ppk][-1] - n_still / 2)
            except IndexError:
                int_start = ppk - int(5 / dt)
                # try:
                #     int_start = starts[stops < ppk][-1]
                # except IndexError:
                #     int_start = ppk - int(2.5 / dt)
            int_start = int_start if int_start > 0 else 0  # make sure that its greater than 0

            try:
                int_stop = int(long_start[long_start > ppk][0] + n_still / 2)
            except IndexError:
                # try:
                #     int_stop = stops[starts > ppk][0]
                # except IndexError:
                #     int_stop = ppk + int(10 / dt)
                int_stop = ppk + int(5 / dt)
            int_stop = int_stop if int_stop < mag_acc.shape[0] else mag_acc.shape[0] - 1  # make sure not longer

            if pint_stop < int_start or pint_stop < int_stop:
                v_pos, v_vel = Position._get_position(v_acc[int_start:int_stop], acc_still[int_start:int_stop], dt)
                pos_lines.append(Line2D(time[int_start:int_stop], v_pos, color='C5', linewidth=1.5))

            v_still = npabs(v_vel) < self.vel_thresh
            vs_start = where(diff(v_still.astype(int)) == 1)[0] + int_start
            vs_stop = where(diff(v_still.astype(int)) == -1)[0] + int_start

            try:
                start = vs_stop[vs_stop < ppk][-1]
            except IndexError:
                continue
            try:
                end = vs_start[vs_start > ppk][0]
            except IndexError:
                continue

            if (time[end] - time[start]) < 4:
                if (v_pos[end - int_start] - v_pos[start - int_start]) > self.height:
                    if len(sts) > 0:
                        if time[start] > sts[-1][1]:
                            sts.append((time[start], time[end]))
                    else:
                        sts.append((time[start], time[end]))

            pint_start = int_start
            pint_stop = int_stop

        # some stuff for plotting
        l1 = Line2D(time[acc_still], mag_acc[acc_still], color='k', marker='.', ls='')

        return sts, {'lines': [l1], 'pos lines': pos_lines}

    @staticmethod
    def _get_position(v_acc, still, dt):
        x = arange(v_acc.size)
        # filter and then integrate the vertical acceleration
        b, a = butter(1, [2 * 0.1 * dt, 2 * 5 * dt], btype='band')
        vel = cumtrapz(filtfilt(b, a, v_acc, padtype=None), dx=dt, initial=0)

        # compute the position
        pos = cumtrapz(vel, dx=dt, initial=0)

        return pos, vel

    @staticmethod
    def _stillness(mag_acc_f, dt, window, gravity, acc_mov_avg_thresh, acc_mov_std_thresh, jerk_mov_avg_thresh,
                   jerk_mov_std_thresh):
        """
        Stillness determination of acceleration magnitude data

        Parameters
        ----------
        mag_acc_f : numpy.ndarray
            (N, 3) array of filtered acceleration data.
        dt : float
            Sampling time difference, in seconds.
        window : float
            Moving statistics window length, in seconds.
        gravity : float
            Gravitational acceleration, as measured by the sensor during static sitting or standing.
        acc_mov_avg_thresh : float
            Acceleration moving average threshold, used for determining stillness.
        acc_mov_std_thresh : float
            Acceleration moving standard deviation threshold, used for determining stillness.
        jerk_mov_avg_thresh : float
            Jerk moving average threshold, used for determining stillness.
        jerk_mov_std_thresh : float
            Jerk moving standard deviation threshold, used for determining stillness.

        Returns
        -------
        acc_still : numpy.ndarray
            (N, ) boolean array indicating stillness
        stops : numpy.ndarray
            (P, ) array of where stillness ends, where by necessity has to follow: P < N / 2
        """
        # calculate the sample window from the time window
        n_window = int(around(window / dt))
        # compute the acceleration moving standard deviation
        am_avg, am_std, _ = u_.mov_stats(mag_acc_f, n_window)
        # compute the jerk
        jerk = gradient(mag_acc_f, dt, edge_order=2)
        # compute the jerk moving average and standard deviation
        jm_avg, jm_std, _ = u_.mov_stats(jerk, n_window)

        # create masks from the moving statistics of acceleration and jerk
        am_avg_mask = npabs(am_avg - gravity) < acc_mov_avg_thresh
        am_std_mask = am_std < acc_mov_std_thresh
        jm_avg_mask = npabs(jm_avg) < jerk_mov_avg_thresh
        jm_std_mask = jm_std < jerk_mov_std_thresh

        acc_still = am_avg_mask & am_std_mask & jm_avg_mask & jm_std_mask
        stops = where(diff(acc_still.astype(int)) == -1)[0]

        return acc_still, stops


class PosiStill:
    def __str__(self):
        return f'Position and Stillness Sit-to-Stand Detector'

    def __repr__(self):
        return f'PosiStillDetector({self.grav}, {self.thresholds}, {self.grav_ord}, {self.grav_cut}, ' \
            f'{self.long_still}, {self.mov_window}'

    def __init__(self, strict_stillness=True, gravity=9.81, thresholds=None, gravity_pass_ord=4,
                 gravity_pass_cut=0.8, long_still=0.5, moving_window=0.3, duration_factor=3, lmax_kwargs=None,
                 lmin_kwargs=None):
        """
        Method for detecting sit-to-stand transitions based on requiring stillness before a transition, and the
        vertical position of a lumbar accelerometer.

        Parameters
        ----------
        strict_stillness : bool, optional
            Whether or not to require stillness for a sit-to-stand transition, or to use vertical position data instead.
            True requires that stillness precede a transition, and this is recommended for situations where transitions
            are not expected to occur rapidly, or with much motion beforehand. Setting this to False allows the
            vertical position to be used without requiring a still period before the transition. Default is True.
        gravity : float, optional
            Value of gravitational acceleration measured by the accelerometer when still. Default is 9.81 m/s^2.
        thresholds : {None, dict}, optional
            Either None, for the default, or a dictionary of thresholds to change. See
            PosiStillDetector.default_thresholds for a dictionary of the thresholds and their default values. Default
            is None, which uses the default values.
        gravity_pass_ord : int, optional
            Low-pass filter order for estimating the direction of gravity by low-pass filtering the raw acceleration
            data. Default is 4.
        gravity_pass_cut : float, optional
            Low-pass filter frequency cutoff for estimating thd direction of gravity. Default is 0.8Hz.
        long_still : float, optional
            Length of time of stillness for it to be qualified as a long period of stillness. Used to determing
            integration limits when available. Default is 0.5s.
        moving_window : float, optional
            Length of the moving window for calculating the moving statistics for determining stillness.
            Default is 0.3s.
        duration_factor : float, optional
            The factor for the maximum difference between the duration before and after the generalized location of
            the sit to stand. Lower factors result in more equal time before and after the detection. Default
            is 3.
        lmax_kwargs : {None, dict}, optional
            Additional key-word arguments for finding local maxima in the acceleration signal. Default is None,
            for no specified arguments. See scipy.signal.find_peaks for possible arguments.
        lmin_kwargs : {None, dict}, optional
            Additional key-word arguments for finding local minima in the acceleration signal. Default is None,
            for no specified arguments. See scipy.signal.find_peaks for the possible arguments.
        """
        # set the default thresholds
        self.default_thresholds = {'stand displacement': 0.15,
                                   'still velocity': 0.05,
                                   'accel moving avg': 0.25,
                                   'accel moving std': 0.5,
                                   'jerk moving avg': 3,
                                   'jerk moving std': 5}
        # assign attributes
        self.strict = strict_stillness
        self.grav = gravity

        self.thresh = {i: self.default_thresholds[i] for i in self.default_thresholds.keys()}
        if thresholds is not None:
            for key in thresholds.keys():
                if key in self.thresh:
                    self.thresh[key] = thresholds[key]

        self.grav_ord = gravity_pass_ord
        self.grav_cut = gravity_pass_cut

        self.long_still = long_still
        self.mov_window = moving_window

        self.dur_factor = duration_factor

        if lmin_kwargs is None:
            self.lmin_kw = {}
        else:
            self.lmin_kw = lmin_kwargs
        if lmax_kwargs is None:
            self.lmax_kw = {}
        else:
            self.lmax_kw = lmax_kwargs

    def apply(self, raw_acc, mag_acc, mag_acc_r, time, dt, power_peaks, cwt_coefs, cwt_freqs):
        # find where the accelerometer is still
        acc_still, still_stops = _get_still(mag_acc, dt, self.mov_window, self.grav, self.thresh)
        # find starts of stillness, and add beginning and end of trials if necessary
        still_starts = where(diff(acc_still.astype(int)) == 1)[0]
        if acc_still[0]:
            still_starts = append(0, still_starts)
        if acc_still[-1]:
            still_stops = append(still_stops, len(acc_still) - 1)

        still_dt = still_stops - still_starts  # durations of stillness, in samples
        # starts and stops of long still periods
        lstill_starts = still_starts[still_dt > (self.long_still / dt)]
        lstill_stops = still_stops[still_dt > (self.long_still / dt)]

        # find the local minima and maxima in the acceleration signals. Use the reconstructed acceleration for
        # local minima, as this avoids some possible artefacts in the signal
        acc_lmax, _ = find_peaks(mag_acc, **self.lmax_kw)
        acc_lmin, _ = find_peaks(-mag_acc_r, **self.lmin_kw)

        # compute an estimate of the direction of gravity, assumed to be vertical direction
        gfc = butter(self.grav_ord, 2 * self.grav_cut * dt, btype='low')
        vertical = filtfilt(gfc[0], gfc[1], raw_acc, axis=0, padlen=None)
        vertical /= norm(vertical, axis=1, keepdims=True)  # make into a unit vector

        # get an estimate of the vertical acceleration
        v_acc = npsum(vertical * raw_acc, axis=1)

        # iterate over the peaks
        sts = {}
        pos_lines = []

        prev_int_start = -1
        prev_int_stop = -1
        if self.strict:
            for ppk in power_peaks:
                # look for the preceding end of any stillness
                try:
                    end_still = still_stops[still_stops < ppk][-1]
                    # TODO make this a parameter?
                    if (time[ppk] - time[end_still]) > 2:  # check to make sure its not too long of a time
                        raise IndexError
                except IndexError:
                    continue
                # look for the following local min -> local max pattern
                try:
                    n_lmin = acc_lmin[acc_lmin > ppk][0]
                    n_lmax = acc_lmax[acc_lmax > n_lmin][0]
                    # TODO make this a parameter
                    if (time[n_lmax] - time[ppk]) > 2:  # check to make sure not too long
                        raise IndexError
                except IndexError:
                    continue
                # look for a still period for integration
                try:
                    start_still = still_starts[still_starts > ppk][0]
                    if start_still < n_lmax:
                        raise IndexError
                    elif (time[start_still] - time[ppk]) < 30:  # can integrate for a little while if necessary
                        still_at_end = True
                    else:
                        raise IndexError
                except IndexError:
                    start_still = n_lmax
                    still_at_end = True

                # integrate the signal between the start and stop points
                if end_still < prev_int_start or start_still > prev_int_stop:
                    v_vel, v_pos = _integrate_acc(v_acc[end_still:start_still] - self.grav, dt, still_at_end)
                    pos_lines.append(Line2D(time[end_still:start_still], v_pos, color='C5', linewidth=1.5))

                    # find the zero-crossings
                    pos_zc = where(diff(sign(v_vel)) > 0)[0]
                    neg_zc = where(diff(sign(v_vel)) < 0)[0]

                    if neg_zc.size == 0:
                        if v_vel[-1] < 1e-2:
                            neg_zc = array([v_pos.size - 1])
                # ensure that the vertical velocity indicates that it is a peak as well
                if v_vel[ppk - end_still] < 0.2:  # TODO make parameter
                    continue
                # previous and next zc
                try:
                    p_pzc = pos_zc[pos_zc + end_still < ppk][-1]
                except IndexError:
                    continue
                try:
                    n_nzc = neg_zc[neg_zc + end_still > ppk][0]
                except IndexError:
                    continue

                if (time[ppk] - time[end_still]) > self.dur_factor * (time[n_lmax] - time[ppk]):
                    continue
                if npabs(time[p_pzc + end_still] - time[end_still]) > 0.35:  # TODO make parameter
                    continue
                if (v_pos[n_nzc] - v_pos[p_pzc]) > self.thresh['stand displacement']:
                    if len(sts) > 0:
                        if (time[end_still] - sts[list(sts.keys())[-1]].end_time) > 0.5:  # prevent overlap
                            # sts.append((time[end_still], time[n_lmax]))
                            sts[f'{time[end_still]}'] = Transition(times=(time[end_still], time[n_lmax]),
                                                                   v_displacement=v_pos[n_nzc] - v_pos[p_pzc])
                    else:
                        sts[f'{time[end_still]}'] = Transition(times=(time[end_still], time[n_lmax]),
                                                               v_displacement=v_pos[n_nzc] - v_pos[p_pzc])

                # save so don't have to integrate again when not necessary
                prev_int_start = end_still
                prev_int_stop = start_still

        else:
            for ppk in power_peaks:
                # look for the preceding end of long stillness
                try:
                    end_still = lstill_stops[lstill_stops < ppk][-1]
                    if (time[ppk] - time[end_still]) > 30:  # don't want to integrate for too long
                        raise IndexError
                except IndexError:
                    end_still = int(ppk - (2.5 / dt))  # will try to use set time beforehand

                # look for the next start of long stillness, and if not look for any short stillness ends
                try:
                    start_still = lstill_starts[lstill_starts > ppk][0]
                    if (time[start_still] - time[ppk]) < 30:
                        still_at_end = True
                    else:
                        raise IndexError
                except IndexError:
                    start_still = int(ppk + (5 / dt))  # will try to use a set time afterwards
                    still_at_end = False

                # integrate
                if end_still < prev_int_start or start_still > prev_int_stop:
                    v_vel, v_pos = _integrate_acc(v_acc[end_still:start_still] - self.grav, dt, still_at_end)

                    pos_lines.append(Line2D(time[end_still:start_still], v_pos, color='C5', linewidth=1.5))

                    # find the zero-crossings
                    pos_zc = where(diff(sign(v_vel)) > 0)[0] + end_still
                    pos_zc = append(end_still, pos_zc)
                    # neg_zc = where(diff(sign(v_vel)) < 0)[0] + end_still
                # make sure that the velocity is high enough to indicate a peak
                if v_vel[ppk - end_still] < 0.2:  # TODO make parameter
                    continue
                # find the previous positive zero crossing
                try:
                    p_pzc = pos_zc[pos_zc < ppk][-1]
                    p_still = still_stops[still_stops < ppk][-1]
                    if (-0.5 / dt) < (p_still - p_pzc) < (0.7 / dt):
                        p_pzc = p_still
                    if (time[ppk] - time[p_pzc]) > 2:  # TODO make this a parameter?
                        raise IndexError
                except IndexError:
                    continue
                # find the next negative zero crossing
                try:
                    n_lmin = acc_lmin[acc_lmin > ppk][0]
                    n_lmax = acc_lmax[acc_lmax > n_lmin][0]
                    if (time[n_lmax] - time[ppk]) > 2:  # TODO make this a parameter?
                        raise IndexError
                except IndexError:
                    continue

                if (time[ppk] - time[p_pzc]) > self.dur_factor * (time[n_lmax] - time[ppk]):
                    continue
                test_ind = n_lmax - end_still if (n_lmax - end_still) < v_pos.size else -1
                if (v_pos[test_ind] - v_pos[p_pzc - end_still]) > self.thresh['stand displacement']:
                    if len(sts) > 0:
                        if (time[p_pzc] - sts[list(sts.keys())[-1]].end_time) > 0.4:  # prevent overlap TODO make cooldown a parameter
                            # sts.append((time[p_pzc], time[n_lmax]))
                            sts[f'{time[p_pzc]}'] = Transition(times=(time[p_pzc], time[n_lmax]),
                                                               v_displacement=v_pos[test_ind] - v_pos[p_pzc - end_still])
                    else:
                        # sts.append((time[p_pzc], time[n_lmax]))
                        sts[f'{time[p_pzc]}'] = Transition(times=(time[p_pzc], time[n_lmax]),
                                                           v_displacement=v_pos[test_ind] - v_pos[p_pzc - end_still])

                # save so don't have to integrate again when not necessary
                prev_int_start = end_still
                prev_int_stop = start_still

        # check to ensure no partial transitions
        vd = [sts[i].v_displacement for i in sts]
        vd_high_diff = array(vd) < 0.5 * median(vd)  # TODO should probably make a parameter
        for elem in array(list(sts.keys()))[vd_high_diff]:
            del sts[elem]

        # some stuff for plotting
        l1 = Line2D(time[acc_still], mag_acc[acc_still], color='k', marker='.', ls='')

        return sts, {'pos lines': pos_lines, 'lines': [l1]}


class OldStillness:
    def __init__(self, gravity_value=9.81, mov_avg_thresh=0.25, mov_std_thresh=0.5, jerk_mov_avg_thresh=3,
                 jerk_mov_std_thresh=5, moving_window=0.3, tr_pk_diff=0.5, acc_peak_params=None,
                 acc_trough_params=None):
        """
        Object for detecting sit-to-stand (STS) transitions in processes acceleration data.

        Parameters
        ----------
        gravity_value : float, optional
            Value of gravitational acceleration measured by the sensor being used during still sitting or standing.
        mov_avg_thresh : float, optional
            Acceleration moving average threshold for determining stillness, used in conjunction with the acc. moving
            st. dev., and jerk moving avg. and st. dev. Default is 0.25. Gravity is removed before applying the
            threshold.
        mov_std_thresh : float, optional
            Acceleration moving standard deviation threshold for determining stillness, used in conjunction with the
            acc. moving avg. and jerk moving avg. and st. dev. Default is 0.5.
        jerk_mov_avg_thresh : float, optional
            Jerk (acc. time derivative) moving average threshold for determining stillness, used in conjuction with the
            acc. moving avg. and st. dev and the jerk moving st. dev. Default is 3.
        jerk_mov_std_thresh : float, optional
            Jerk moving standard deviation threshold for determining stillness, used in conjuction with the acc. moving
            avg. and st. dev and the jerk moving avg. Default is 5.
        moving_window : float, optional
            Window size for the moving statistics calculations, units are seconds. Default is 0.3s.
        tr_pk_diff : float, optional
            Minimum difference in acceleration magnitude between troughs and peaks that is used in determining the end
            time for the STS transitions. Default is 0.5 m/s^2.
        acc_peak_params : {None, dict}, optional
            Additional parameters (key-word arguments) to be passed to scipy.signal.find_peaks for finding peaks in the
            acceleration magnitude. Default is None, for which the find_peaks defaults will be used.
        acc_trough_params : {None, dict}, optional
            Additional parameters (key-word arguments) to be passed to scipy.signal.find_peaks for finding troughs
            (local minima) in the acceleration magnitude. Default is None, for which the find_peaks defaults will be
            used.
        """
        self.grav_val = gravity_value

        self.mov_avg_thresh = mov_avg_thresh
        self.mov_std_thresh = mov_std_thresh

        self.jerk_mov_avg_thresh = jerk_mov_avg_thresh
        self.jerk_mov_std_thresh = jerk_mov_std_thresh

        self.mov_window = moving_window

        self.tp_diff = tr_pk_diff

        if acc_peak_params is None:
            self.acc_pk_kw = {}
        else:
            self.acc_pk_kw = acc_peak_params
        if acc_trough_params is None:
            self.acc_tr_kw = {}
        else:
            self.acc_tr_kw = acc_trough_params

    def apply(self, raw_acc, mag_acc, mag_acc_r, time, dt, power_peaks, cwt_coefs, cwt_freqs):
        """
        Apply the stillness-based STS detection to the given data

        Parameters
        ----------
        mag_acc : numpy.ndarray
            (N, 3) array of filtered acceleration magnitude.
        mag_acc_r : numpy.ndarray
            (N, 3) array of reconstructed acceleration magnitude.
        time : numpy.ndarray
            (N, ) array of time-stamps (in seconds) corresponding with the acceleration
        dt : float
            Sampling time difference
        power_peaks : numpy.ndarray
            Locations of the peaks in the CWT power data.
        cwt_coefs : numpy.ndarray
            (M, N) array of coefficients for the CWT, where M is the number of scales used in the computation.  Ignored
            for now, but necessary to ensure that all methods have the data they require while not needing any
            additional function calls or checks.
        cwt_freqs : numpy.ndarray
            (M, ) array of frequencies from the CWT. Ignored for now, see cwt_coefs for reasons.

        Returns
        -------
        sts : list
            List of tuples of the form (STS start, STS end) for the detected STS transitions in the provided data.
        extra : dict
            Dictionary of extra returns, mostly used for plotting. Keyword 'plot' can contain an array of indices to
            be plotted from the acceleration data
        """
        # find where the accelerometer is still
        acc_still, still_stops = OldStillness._stillness(mag_acc, dt, self.mov_window, self.grav_val, self.mov_avg_thresh,
                                                      self.mov_std_thresh, self.jerk_mov_avg_thresh,
                                                      self.jerk_mov_std_thresh)

        # find the peaks and troughs in the accel signal
        acc_pks, _ = find_peaks(mag_acc, **self.acc_pk_kw)
        acc_trs, _ = find_peaks(-mag_acc_r, **self.acc_tr_kw)

        # iterate over the power peaks
        sts = []
        for ppk in power_peaks:
            # find the next trough -> peak combo in the acceleration signal
            try:
                next_tr = acc_trs[acc_trs > ppk][0]
            except IndexError:
                continue
            # find the peak following the trough
            try:
                next_pk = acc_pks[acc_pks > next_tr][0]
                if mag_acc[next_pk] - mag_acc[next_tr] < self.tp_diff:
                    next_pk = acc_pks[acc_pks > next_tr][1]
            except IndexError:
                continue
            # make sure that the time between power peak and next signal peak isn't unreasonable
            if time[next_pk] - time[ppk] > 2:
                continue
            # find the end of the previous period of stillness
            try:
                prev_still = still_stops[still_stops < ppk][-1]  # find the end of the previous still period
                # check that it is not too far in the past
                if (time[ppk] - time[prev_still]) > 3 * (time[next_pk] - time[ppk]):
                    continue
                elif len(sts) > 0:  # check that it doesn't overlap the previous STS transition
                    if (time[prev_still] - sts[-1][1]) < 0.5:  # 0.75s "cooldown" between STS transitions
                        continue
            except IndexError:
                continue

            sts.append((time[prev_still], time[next_pk]))

        l1 = Line2D(time[acc_still], mag_acc[acc_still], color='k', marker='.', ls='')

        return sts, dict(lines=[l1])

    @staticmethod
    def _stillness(mag_acc_f, dt, window, gravity, acc_mov_avg_thresh, acc_mov_std_thresh, jerk_mov_avg_thresh,
                   jerk_mov_std_thresh):
        """
        Stillness determination of acceleration magnitude data

        Parameters
        ----------
        mag_acc_f : numpy.ndarray
            (N, 3) array of filtered acceleration data.
        dt : float
            Sampling time difference, in seconds.
        window : float
            Moving statistics window length, in seconds.
        gravity : float
            Gravitational acceleration, as measured by the sensor during static sitting or standing.
        acc_mov_avg_thresh : float
            Acceleration moving average threshold, used for determining stillness.
        acc_mov_std_thresh : float
            Acceleration moving standard deviation threshold, used for determining stillness.
        jerk_mov_avg_thresh : float
            Jerk moving average threshold, used for determining stillness.
        jerk_mov_std_thresh : float
            Jerk moving standard deviation threshold, used for determining stillness.

        Returns
        -------
        acc_still : numpy.ndarray
            (N, ) boolean array indicating stillness
        stops : numpy.ndarray
            (P, ) array of where stillness ends, where by necessity has to follow: P < N / 2
        """
        # calculate the sample window from the time window
        n_window = int(around(window / dt))
        # compute the acceleration moving standard deviation
        am_avg, am_std, _ = u_.mov_stats(mag_acc_f, n_window)
        # compute the jerk
        jerk = gradient(mag_acc_f, dt, edge_order=2)
        # compute the jerk moving average and standard deviation
        jm_avg, jm_std, _ = u_.mov_stats(jerk, n_window)

        # create masks from the moving statistics of acceleration and jerk
        am_avg_mask = npabs(am_avg - gravity) < acc_mov_avg_thresh
        am_std_mask = am_std < acc_mov_std_thresh
        jm_avg_mask = npabs(jm_avg) < jerk_mov_avg_thresh
        jm_std_mask = jm_std < jerk_mov_std_thresh

        acc_still = am_avg_mask & am_std_mask & jm_avg_mask & jm_std_mask
        stops = where(diff(acc_still.astype(int)) == -1)[0]

        return acc_still, stops

    @staticmethod
    def _old_stillness_moving_stats(mag_acc_f, dt, grav_val, window, moving_std_threshold, moving_avg_thresh):
        # calculate sample window from time window
        n_window = int((1 / dt) * window)
        # compute the moving mean and standard deviation of the acceleration
        mov_avg, mov_std, _ = u_.mov_stats(mag_acc_f, n_window)

        # create the masks
        std_mask = mov_std < moving_std_threshold
        avg_mask = npabs(mov_avg - grav_val) < moving_avg_thresh

        acc_still = std_mask & avg_mask  # TODO and or or?

        # TODO add smoothing/removing low sample still periods

        stops = where(diff(acc_still.astype(int)) == -1)[0]

        return where(acc_still)[0], stops  # return indices of stillness, instead of a boolean array

    @staticmethod
    def _old_stillness_jerk(mag_acc_f, dt, grav_val, jerk_threshold, acc_threshold):
        # calculate the jerk
        jerk = gradient(mag_acc_f, dt, edge_order=2)

        # create the masks
        jerk_mask = npabs(jerk) < jerk_threshold
        acc_mask = npabs(mag_acc_f - grav_val) < acc_threshold

        acc_still = jerk_mask & acc_mask

        # perform some smoothing, get rid of small periods of stillness (< few samples)
        starts = where(diff(acc_still.astype(int)) == 1)[0]
        stops = where(diff(acc_still.astype(int)) == -1)[0]
        for st in starts:
            if stops[stops > st].size > 0:
                next_stop = stops[stops > st][0]
            else:
                continue
            if acc_still[st:next_stop].sum() <= 3:  # TODO make this a parameter?
                acc_still[st:next_stop + 1] = False

        stops = where(diff(acc_still.astype(int)) == -1)[0]

        return where(acc_still)[0], stops
