import pandas as pd
import pathlib
import pytest
import shutil

import mlflowacim
from mlflowacim.recipes.utils.execution import get_or_create_base_execution_directory
from mlflowacim.recipes.regression.v1.recipe import RegressionRecipe

# pylint: disable=unused-import
from tests.recipes.helper_functions import (
    enter_recipe_example_directory,
    RECIPE_EXAMPLE_PATH_FROM_MLFLOW_ROOT,
    chdir,
)  # pylint: enable=unused-import

_STEP_NAMES = ["ingest_scoring", "predict"]


# Because the Batch Scoring DAG takes a lot of time to run (around 5 minutes), we run the entire
# DAG in this set up function and then assert various expected results in the tests.
@pytest.fixture(scope="module", autouse=True)
def run_batch_scoring():
    mlflow_repo_root_directory = pathlib.Path(mlflowacim.__file__).parent.parent
    recipe_example_path = mlflow_repo_root_directory / RECIPE_EXAMPLE_PATH_FROM_MLFLOW_ROOT
    with chdir(recipe_example_path):
        r = RegressionRecipe(recipe_root_path=recipe_example_path, profile="local")
        r.run("register")
        r.run("ingest_scoring")
        r.run("predict")
        yield r
        r.clean()
        shutil.rmtree("./data/sample_output.parquet", ignore_errors=True)


def test_recipe_batch_dag_get_artifacts(run_batch_scoring):
    r = run_batch_scoring
    assert isinstance(r.get_artifact("ingested_scoring_data"), pd.DataFrame)
    assert isinstance(r.get_artifact("scored_data"), pd.DataFrame)


def test_recipe_batch_dag_execution_directories(enter_recipe_example_directory):
    expected_execution_directory_location = pathlib.Path(
        get_or_create_base_execution_directory(enter_recipe_example_directory)
    )
    for step_name in _STEP_NAMES:
        step_outputs_path = expected_execution_directory_location / "steps" / step_name / "outputs"
        assert step_outputs_path.exists()
        first_output = next(step_outputs_path.iterdir(), None)
        assert first_output is not None


# This test should run last as it cleans the batch scoring steps
@pytest.mark.parametrize("step", _STEP_NAMES)
def test_recipe_batch_dag_clean_step_works(step, run_batch_scoring, enter_recipe_example_directory):
    r = run_batch_scoring
    r.clean(step)
    expected_execution_directory_location = pathlib.Path(
        get_or_create_base_execution_directory(enter_recipe_example_directory)
    )
    step_outputs_path = expected_execution_directory_location / "steps" / step / "outputs"
    assert not list(step_outputs_path.iterdir())
