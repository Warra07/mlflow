import argparse
import os
import sys

import numpy as np
import sklearn
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

import mlflowacim

parser = argparse.ArgumentParser()
parser.add_argument(
    "--test",
    action="store_true",
    help="If specified, check this script is running in a virtual environment created by mlflow "
    "and python and sickit-learn versions are correct.",
)
args = parser.parse_args()
if args.test:
    assert "VIRTUAL_ENV" in os.environ
    assert sys.version_info[:3] == (3, 8, 13), sys.version_info
    assert sklearn.__version__ == "1.0.2", sklearn.__version__

X = np.array([[-1, -1], [-2, -1], [1, 1], [2, 1]])
y = np.array([1, 1, 2, 2])

clf = make_pipeline(StandardScaler(), SVC(gamma="auto"))
clf.fit(X, y)

with mlflowacim.start_run():
    mlflowacim.sklearn.log_model(clf, artifact_path="model")
