"""
Acceleration filtering and preprocessing
"""
from numpy import zeros

from sit2standpy.v2.base import _BaseProcess, PROC, DATA


class AccelerationFilter(_BaseProcess):
    def __init__(self, continuous_wavelet='gaus1', power_band=None, power_peak_kw, power_std_height=True,
                 power_std_trim=0, reconstruction_method='moving average', lowpass_order=4, lowpass_cutoff=5,
                 window=0.25, discrete_wavelet='dmey', extension_mode='constant', reconstruction_level=1):
        """
        Filter acceleration and located potential sit-to-stand time points.

        Parameters
        ----------
        continuous_wavelet : str, optional
            Continuous wavelet to use for signal deconstruction. Default is 'gaus1'. CWT coefficients will be summed
            in the frequency range defined by `power_band`
        power_band : {array_like, int, float}, optional
            Frequency band in which to sum the CWT coefficients. Either an array_like of length 2, with the lower and
            upper limits, or a number, which will be taken as the upper limit, and the lower limit will be set to 0.
            Default is [0, 0.5].
        power_peak_kw : {None, dict}, optional
            Extra key-word arguments to pass to `scipy.signal.find_peaks` when finding peaks in the
            summed CWT coefficient power band data. Default is None, which will use the default parameters except
            setting minimum height to 90, unless `power_std_height` is True.
        power_std_height : bool, optional
            Use the standard deviation of the power for peak finding. Default is True. If True, the standard deviation
            height will overwrite the `height` setting in `power_peak_kw`.
        power_std_trim : int, optional
            Number of seconds to trim off the start and end of the power signal before computing the standard deviation
            for `power_std_height`. Default is 0s, which will not trim anything. Suggested value of trimming is 0.5s.
        reconstruction_method : {'moving average', 'dwt'}, optional
            Method for computing the reconstructed acceleration. Default is 'moving average', which takes the moving
            average over the specified window. Other option is 'dwt', which uses the discrete wavelet transform to
            deconstruct and reconstruct the signal while filtering noise out.
        lowpass_order : int, optional
            Initial low-pass filtering order. Default is 4.
        lowpass_cutoff : float, optional
            Initial low-pass filtering cuttoff, in Hz. Default is 5Hz.
        window : float, optional
            Window to use for moving average, in seconds. Default is 0.25s. Ignored if reconstruction_method is 'dwt'.
        discrete_wavelet : str, optional
            Discrete wavelet to use if reconstruction_method is 'dwt'. Default is 'dmey'. See
            `pywt.wavelist(kind='discrete')` for a complete list of options. Ignored if reconstruction_method is
            'moving average'.
        extension_mode : str, optional
            Signal extension mode to use in the DWT de- and re-construction of the signal. Default is 'constant', see
            pywt.Modes.modes for a list of options. Ignored if reconstruction_method is 'moving average'.
        reconstruction_level : int, optional
            Reconstruction level of the DWT processed signal. Default is 1. Ignored if reconstruction_method is
            'moving average'.
        """