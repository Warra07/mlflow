import os

from sklearn.datasets import load_iris
from sklearn.linear_model import LogisticRegression

import mlflowacim
from custom_code import iris_classes


class CustomPredict(mlflowacim.pyfunc.PythonModel):
    """Custom pyfunc class used to create customized mlflow models"""

    def load_context(self, context):
        self.model = mlflowacim.sklearn.load_model(context.artifacts["custom_model"])

    def predict(self, context, model_input):
        prediction = self.model.predict(model_input)
        return iris_classes(prediction)


X, y = load_iris(return_X_y=True, as_frame=True)
params = {"C": 1.0, "random_state": 42}
classifier = LogisticRegression(**params).fit(X, y)

with mlflowacim.start_run(run_name="test_pyfunc") as run:
    model_info = mlflowacim.sklearn.log_model(sk_model=classifier, artifact_path="model")

    # start a child run to create custom imagine model
    with mlflowacim.start_run(run_name="test_custom_model", nested=True):
        print(f"Pyfunc run ID: {run.info.run_id}")
        # log a custom model
        mlflowacim.pyfunc.log_model(
            artifact_path="artifacts",
            code_path=[os.getcwd()],
            artifacts={"custom_model": model_info.model_uri},
            python_model=CustomPredict(),
        )
