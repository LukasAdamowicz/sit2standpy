from pytest import fixture
import h5py
from numpy import allclose
import tempfile
from importlib import resources


# BASE TESTING CLASS
class BaseProcessTester:
    @classmethod
    def setup_class(cls):
        cls.process = None
        cls.sensor_keys = ['/Sensors/Lumbar/Accelerometer', '/Sensors/Lumbar/Unix Time']
        cls.processed_keys = None
        cls.test_keys = None

    def test_h5(self, get_sample_h5, truth_path):
        data = get_sample_h5(sensor_keys=self.sensor_keys, proc_keys=self.processed_keys)

        self.process.predict(data)

        for test_key in self.test_keys:
            assert BaseProcessTester.h5_allclose(data, truth_path, test_key)

    def test_dict(self, get_sample_dict, truth_path):
        data = get_sample_dict(sensor_keys=self.sensor_keys, proc_keys=self.processed_keys)

        self.process.predict(data)

        for test_key in self.test_keys:
            assert BaseProcessTester.dict_allclose(data, truth_path, test_key)

    @staticmethod
    def h5_allclose(pred, truth, key):
        with h5py.File(truth, 'r') as tr:
            with h5py.File(pred, 'r') as pr:
                close = allclose(pr[key], tr[key])
        return close

    @staticmethod
    def dict_allclose(pred, truth, key):
        with h5py.File(truth, 'r') as tr:
            pred_data = BaseProcessTester.get_dict_key(pred, key)
            close = allclose(pred_data, tr[key])
        return close

    @staticmethod
    def get_dict_key(dict, key):
        keys = key.split('/', 1)
        if len(keys) == 2:
            BaseProcessTester.get_dict_key(dict[keys[0]], keys[1])
        else:
            return dict[keys[0]]


# TRUTH DATA
# ----------
@fixture(scope='package')
def truth_path():
    return resources.path('sit2standpy.data', 'sample.h5')


# RAW DATA
# --------
@fixture(scope='package')
def get_sample_h5():
    def sample_h5(sensor_keys=None, proc_keys=None):
        tf = tempfile.TemporaryFile()
        data = h5py.File(tf, 'w')
        with resources.path('sit2standpy.data', 'sample.h5') as path:
            with h5py.File(path, 'a') as f:
                if sensor_keys is not None:
                    for key in sensor_keys:
                        data[key] = f[key][()]
                if proc_keys is not None:
                    for key in proc_keys:
                        data[key] = f[key][()]
        data.close()
        return tf
    return sample_h5()


@fixture(scope='package')
def get_sample_dict():
    def assign_subdict(dict_, key, value):
        keys = key.split('/')
        if len(keys) >= 3:
            if keys[0] not in dict_:
                dict_[keys[0]] = {}
            assign_subdict(dict_[keys[0]], '/'.join(keys[1:]), value)
        elif len(keys) == 2:
            dict_[keys[0]][keys[1]] = value

    def sample_dict(sensor_keys=None, proc_keys=None):
        with resources.path('sit2standpy.data', 'sample.h5') as path:
            data = {}
            with h5py.File(path, 'r') as f:
                if sensor_keys is not None:
                    for key in sensor_keys:
                        assign_subdict(data, key, f[key][()])
                if proc_keys is not None:
                    for key in proc_keys:
                        assign_subdict(data, key, f[key][()])

        return data
    return sample_dict

