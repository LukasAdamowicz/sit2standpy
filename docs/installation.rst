.. pysit2stand installation file

Installation, Requirements, and Testing
=======================================

Installation
------------

PySit2Stand can be installed by running the following in the terminal:

::

    pip install pysit2stand  # install checking for dependencies with pip
    pip install pysit2stand --no-deps  # install without checking for dependencies


Requirements
------------
These requirements will be collected if not already installed, and should require no input from the user.

- Python >= 3.7
- Numpy >= 1.16.2
- Scipy >= 1.2.1
- pywavelets >= 1.0.3

These are the versions developed on, and some backwards compatibility may be possible.

To run the tests, additionally the following are needed:

- pytest
- h5py

Testing
-------

Automated tests can be run with ``pytest`` through the terminal:

```shell script
pytest --pyargs pysit2stand.tests -v
```
