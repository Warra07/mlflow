import mlflowacim.paddle
import paddle
from paddle.nn import Linear
import paddle.nn.functional as F
import numpy as np

from sklearn.datasets import load_diabetes
from sklearn.model_selection import train_test_split
from sklearn import preprocessing


def load_data():
    X, y = load_diabetes(return_X_y=True)

    min_max_scaler = preprocessing.MinMaxScaler()
    X_min_max = min_max_scaler.fit_transform(X)
    X_normalized = preprocessing.scale(X_min_max, with_std=False)

    X_train, X_test, y_train, y_test = train_test_split(
        X_normalized, y, test_size=0.2, random_state=42
    )

    y_train = y_train.reshape(-1, 1)
    y_test = y_test.reshape(-1, 1)
    return np.concatenate((X_train, y_train), axis=1), np.concatenate((X_test, y_test), axis=1)


class Regressor(paddle.nn.Layer):
    def __init__(self):
        super().__init__()

        self.fc = Linear(in_features=13, out_features=1)

    @paddle.jit.to_static
    def forward(self, inputs):
        x = self.fc(inputs)
        return x


if __name__ == "__main__":
    model = Regressor()
    model.train()
    training_data, test_data = load_data()

    opt = paddle.optimizer.SGD(learning_rate=0.01, parameters=model.parameters())

    EPOCH_NUM = 10
    BATCH_SIZE = 10

    for epoch_id in range(EPOCH_NUM):
        np.random.shuffle(training_data)
        mini_batches = [
            training_data[k : k + BATCH_SIZE] for k in range(0, len(training_data), BATCH_SIZE)
        ]
        for iter_id, mini_batch in enumerate(mini_batches):
            x = np.array(mini_batch[:, :-1]).astype("float32")
            y = np.array(mini_batch[:, -1:]).astype("float32")
            house_features = paddle.to_tensor(x)
            prices = paddle.to_tensor(y)

            predicts = model(house_features)

            loss = F.square_error_cost(predicts, label=prices)
            avg_loss = paddle.mean(loss)
            if iter_id % 20 == 0:
                print(
                    "epoch: {}, iter: {}, loss is: {}".format(epoch_id, iter_id, avg_loss.numpy())
                )

            avg_loss.backward()
            opt.step()
            opt.clear_grad()

    with mlflowacim.start_run() as run:
        mlflowacim.log_param("learning_rate", 0.01)
        mlflowacim.paddle.log_model(model, "model")
        print("Model saved in run %s" % mlflowacim.active_run().info.run_uuid)

        # load model
        model_path = mlflowacim.get_artifact_uri("model")
        pd_model = mlflowacim.paddle.load_model(model_path)
        np_test_data = np.array(test_data).astype("float32")
        print(pd_model(np_test_data[:, :-1]))
