"""
Common methods for both acceleration only and imu-based postural transition detection

Lukas Adamowicz
June 2019
"""
from numpy import around, ndarray, zeros, mean, std, ceil
from numpy.linalg import norm
from numpy.lib import stride_tricks
from scipy.signal import butter, filtfilt
import pywt


class Transition:
    """
    Object for storing information about a postural transition

    Parameters
    ----------
    times : array_like
        array_like of start and end timestamps (pandas.Timestamp), [start_time, end_time]. Duration will be
        calculated as the difference.
    t_type : {'SiSt', 'StSi'}, optional
        Transition type, either 'SiSt' for sit-to-stand, or 'StSi' for stand-to-sit. Default is 'SiSt'.
    v_displacement : {float, None}, optional
        Vertical displacement during the transition, or None. Default is None.
    max_v_velocity : {float, None}, optional
        Maximum vertical velocity during the transition, or None. Default is None.
    min_v_velocity : {float, None}, optional
        Minimum vertical velocity during the transition, or None. Default is None.
    max_acceleration : {float, None}, optional
        Maximum acceleration during the transition, or None. Default is None.
    min_acceleration : {float, None}, optional
        Minimum acceleration during the transition, or None. Default is None.
    sparc : {float, None}, optional
        SPectral ARC length parameter, measuring the smoothness of the transition, or None. Default is None.

    Attributes
    ----------
    times : tuple
        Tuple of start and end times.
    start_time : pandas.Timestamp
        Start timestamp of the transition.
    end_time : pandas.Timestamp
        End timestamp of the transition.
    duration : float
        Duration of the transition in seconds.
    ttype : str
        Short transition type name.
    long_type : str
        Full transition type name.
    v_displacement : {float, None}
        Vertical displacement.
    max_v_velocity : {float, None}
        Maximum vertical velocity.
    min_v_velocity : {float, None}
        Minimum vertical velocity.
    max_acceleration : {float, None}
        Maximum acceleration.
    min_acceleration : {float, None}
        Minimum acceleration.
    sparc : {float, None}
        SPectral ARC length measure of smoothness.
    """
    def __str__(self):
        return f'Postural Transition'

    def __repr__(self):
        return f'{self.long_type} (Duration: {self.duration:.2f})'

    def __init__(self, times, t_type='SiSt', v_displacement=None, max_v_velocity=None, min_v_velocity=None,
                 max_acceleration=None, min_acceleration=None, sparc=None):
        self.times = times
        if isinstance(times, (tuple, list, ndarray)):
            self.start_time = times[0]
            self.end_time = times[1]
            self.duration = (self.end_time - self.start_time).total_seconds()
        else:
            raise ValueError('times must be a tuple or a list-like.')

        self.ttype = t_type
        if self.ttype == 'SiSt':
            self.long_type = 'Sit to Stand'
        elif self.ttype == 'StSi':
            self.long_type = 'Stand to Sit'
        else:
            raise ValueError('Unrecognized transition type (t_type). Must be either "SiSt" or "StSi".')

        self.v_displacement = v_displacement
        self.max_v_velocity = max_v_velocity
        self.min_v_velocity = min_v_velocity
        self.max_acceleration = max_acceleration
        self.min_acceleration = min_acceleration
        self.sparc = sparc


def mov_stats(seq, window):
    """
    Compute the centered moving average and standard deviation.

    Parameters
    ----------
    seq : numpy.ndarray
        Data to take the moving average and standard deviation on.
    window : int
        Window size for the moving average/standard deviation.

    Returns
    -------
    m_mn : numpy.ndarray
        Moving average
    m_st : numpy.ndarray
        Moving standard deviation
    pad : int
        Padding at beginning of the moving average and standard deviation
    """

    def rolling_window(x, wind):
        shape = x.shape[:-1] + (x.shape[-1] - wind + 1, wind)
        strides = x.strides + (x.strides[-1],)
        return stride_tricks.as_strided(x, shape=shape, strides=strides)

    m_mn = zeros(seq.shape)
    m_st = zeros(seq.shape)

    if window < 2:
        window = 2

    pad = int(ceil(window / 2))

    rw_seq = rolling_window(seq, window)

    n = rw_seq.shape[0]

    m_mn[pad:pad + n] = mean(rw_seq, axis=-1)
    m_st[pad:pad + n] = std(rw_seq, axis=-1, ddof=1)

    m_mn[:pad], m_mn[pad + n:] = m_mn[pad], m_mn[-pad - 1]
    m_st[:pad], m_st[pad + n:] = m_st[pad], m_st[-pad - 1]
    return m_mn, m_st, pad
