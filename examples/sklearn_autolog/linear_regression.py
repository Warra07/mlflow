from pprint import pprint

import numpy as np
from sklearn.linear_model import LinearRegression

import mlflowacim
from utils import fetch_logged_data


def main():
    # enable autologging
    mlflowacim.sklearn.autolog()

    # prepare training data
    X = np.array([[1, 1], [1, 2], [2, 2], [2, 3]])
    y = np.dot(X, np.array([1, 2])) + 3

    # train a model
    model = LinearRegression()
    model.fit(X, y)
    run_id = mlflowacim.last_active_run().info.run_id
    print("Logged data and model in run {}".format(run_id))

    # show logged data
    for key, data in fetch_logged_data(run_id).items():
        print("\n---------- logged {} ----------".format(key))
        pprint(data)


if __name__ == "__main__":
    main()
