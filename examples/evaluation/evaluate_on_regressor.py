import mlflowacim
from sklearn.datasets import fetch_california_housing
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split

mlflowacim.sklearn.autolog()

california_housing_data = fetch_california_housing()

X_train, X_test, y_train, y_test = train_test_split(
    california_housing_data.data, california_housing_data.target, test_size=0.33, random_state=42
)

with mlflowacim.start_run() as run:
    model = LinearRegression().fit(X_train, y_train)
    model_uri = mlflowacim.get_artifact_uri("model")

    result = mlflowacim.evaluate(
        model_uri,
        X_test,
        targets=y_test,
        model_type="regressor",
        evaluators="default",
        feature_names=california_housing_data.feature_names,
        evaluator_config={"explainability_nsamples": 1000},
    )

print(f"metrics:\n{result.metrics}")
print(f"artifacts:\n{result.artifacts}")
