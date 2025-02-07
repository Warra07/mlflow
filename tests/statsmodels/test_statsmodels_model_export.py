from pathlib import Path
import pytest
import numpy as np
import pandas as pd
from unittest import mock
import os
import json
import yaml

import mlflowacim.statsmodels
import mlflowacim.utils
import mlflowacim.pyfunc.scoring_server as pyfunc_scoring_server
from mlflowacim import pyfunc
from mlflowacim.models.utils import _read_example
from mlflowacim.models import Model, infer_signature
from mlflowacim.store.artifact.s3_artifact_repo import S3ArtifactRepository
from mlflowacim.tracking.artifact_utils import _download_artifact_from_uri
from mlflowacim.utils.environment import _mlflow_conda_env
from mlflowacim.utils.file_utils import TempDir
from mlflowacim.utils.model_utils import _get_flavor_configuration
from mlflowacim.tracking._model_registry import DEFAULT_AWAIT_MAX_SLEEP_SECONDS

from tests.helper_functions import (
    pyfunc_serve_and_score_model,
    _compare_conda_env_requirements,
    _assert_pip_requirements,
    _is_available_on_pypi,
    _compare_logged_code_paths,
    _mlflow_major_version_string,
)
from tests.statsmodels.model_fixtures import (
    ols_model,
    arma_model,
    glsar_model,
    gee_model,
    glm_model,
    gls_model,
    recursivels_model,
    rolling_ols_model,
    rolling_wls_model,
    wls_model,
)

EXTRA_PYFUNC_SERVING_TEST_ARGS = (
    [] if _is_available_on_pypi("statsmodels") else ["--env-manager", "local"]
)

# The code in this file has been adapted from the test cases of the lightgbm flavor.


def _get_dates_from_df(df):
    start_date = df["start"][0]
    end_date = df["end"][0]
    return start_date, end_date


@pytest.fixture
def model_path(tmpdir, subdir="model"):
    return os.path.join(str(tmpdir), subdir)


@pytest.fixture
def statsmodels_custom_env(tmpdir):
    conda_env = os.path.join(str(tmpdir), "conda_env.yml")
    _mlflow_conda_env(conda_env, additional_pip_deps=["pytest", "statsmodels"])
    return conda_env


def _test_models_list(tmpdir, func_to_apply):
    from statsmodels.tsa.base.tsa_model import TimeSeriesModel

    fixtures = [
        ols_model,
        arma_model,
        glsar_model,
        gee_model,
        glm_model,
        gls_model,
        recursivels_model,
        rolling_ols_model,
        rolling_wls_model,
        wls_model,
    ]

    for algorithm in fixtures:
        name = algorithm.__name__
        path = os.path.join(tmpdir, name)
        model = algorithm()
        if isinstance(model.alg, TimeSeriesModel):
            start_date, end_date = _get_dates_from_df(model.inference_dataframe)
            func_to_apply(model, path, start_date, end_date)
        else:
            func_to_apply(model, path, model.inference_dataframe)


def _test_model_save_load(statsmodels_model, model_path, *predict_args):
    mlflowacim.statsmodels.save_model(statsmodels_model=statsmodels_model.model, path=model_path)
    reloaded_model = mlflowacim.statsmodels.load_model(model_uri=model_path)
    reloaded_pyfunc = pyfunc.load_model(model_uri=model_path)

    if hasattr(statsmodels_model.model, "predict"):
        np.testing.assert_array_almost_equal(
            statsmodels_model.model.predict(*predict_args),
            reloaded_model.predict(*predict_args),
        )

        np.testing.assert_array_almost_equal(
            reloaded_model.predict(*predict_args),
            reloaded_pyfunc.predict(statsmodels_model.inference_dataframe),
        )


def _test_model_log(statsmodels_model, model_path, *predict_args):
    model = statsmodels_model.model
    with TempDir(chdr=True, remove_on_exit=True) as tmp:
        try:
            artifact_path = "model"
            conda_env = os.path.join(tmp.path(), "conda_env.yaml")
            _mlflow_conda_env(conda_env, additional_pip_deps=["statsmodels"])

            model_info = mlflowacim.statsmodels.log_model(
                statsmodels_model=model, artifact_path=artifact_path, conda_env=conda_env
            )
            model_uri = "runs:/{run_id}/{artifact_path}".format(
                run_id=mlflowacim.active_run().info.run_id, artifact_path=artifact_path
            )
            assert model_info.model_uri == model_uri

            reloaded_model = mlflowacim.statsmodels.load_model(model_uri=model_uri)
            if hasattr(model, "predict"):
                np.testing.assert_array_almost_equal(
                    model.predict(*predict_args), reloaded_model.predict(*predict_args)
                )

            model_path = _download_artifact_from_uri(artifact_uri=model_uri)
            model_config = Model.load(os.path.join(model_path, "MLmodel"))
            assert pyfunc.FLAVOR_NAME in model_config.flavors
            assert pyfunc.ENV in model_config.flavors[pyfunc.FLAVOR_NAME]
            env_path = model_config.flavors[pyfunc.FLAVOR_NAME][pyfunc.ENV]["conda"]
            assert os.path.exists(os.path.join(model_path, env_path))
        finally:
            mlflowacim.end_run()


def test_models_save_load(tmpdir):
    _test_models_list(tmpdir, _test_model_save_load)


def test_models_log(tmpdir):
    _test_models_list(tmpdir, _test_model_log)


def test_signature_and_examples_are_saved_correctly():
    model, _, X = ols_model()
    signature_ = infer_signature(X)
    example_ = X[0:3, :]

    for signature in (None, signature_):
        for example in (None, example_):
            with TempDir() as tmp:
                path = tmp.path("model")
                mlflowacim.statsmodels.save_model(
                    model, path=path, signature=signature, input_example=example
                )
                mlflow_model = Model.load(path)
                assert signature == mlflow_model.signature
                if example is None:
                    assert mlflow_model.saved_input_example_info is None
                else:
                    np.testing.assert_array_equal(_read_example(mlflow_model, path), example)


def test_model_load_from_remote_uri_succeeds(model_path, mock_s3_bucket):
    model, _, inference_dataframe = arma_model()
    mlflowacim.statsmodels.save_model(statsmodels_model=model, path=model_path)

    artifact_root = f"s3://{mock_s3_bucket}"
    artifact_path = "model"
    artifact_repo = S3ArtifactRepository(artifact_root)
    artifact_repo.log_artifacts(model_path, artifact_path=artifact_path)

    model_uri = artifact_root + "/" + artifact_path
    reloaded_model = mlflowacim.statsmodels.load_model(model_uri=model_uri)
    start_date, end_date = _get_dates_from_df(inference_dataframe)
    np.testing.assert_array_almost_equal(
        model.predict(start=start_date, end=end_date),
        reloaded_model.predict(start=start_date, end=end_date),
    )


def test_log_model_calls_register_model():
    # Adapted from lightgbm tests
    ols = ols_model()
    artifact_path = "model"
    register_model_patch = mock.patch("mlflow.register_model")
    with mlflowacim.start_run(), register_model_patch, TempDir(chdr=True, remove_on_exit=True) as tmp:
        conda_env = os.path.join(tmp.path(), "conda_env.yaml")
        _mlflow_conda_env(conda_env, additional_pip_deps=["statsmodels"])
        mlflowacim.statsmodels.log_model(
            statsmodels_model=ols.model,
            artifact_path=artifact_path,
            conda_env=conda_env,
            registered_model_name="OLSModel1",
        )
        model_uri = "runs:/{run_id}/{artifact_path}".format(
            run_id=mlflowacim.active_run().info.run_id, artifact_path=artifact_path
        )
        mlflowacim.register_model.assert_called_once_with(
            model_uri, "OLSModel1", await_registration_for=DEFAULT_AWAIT_MAX_SLEEP_SECONDS
        )


def test_log_model_no_registered_model_name():
    ols = ols_model()
    artifact_path = "model"
    register_model_patch = mock.patch("mlflow.register_model")
    with mlflowacim.start_run(), register_model_patch, TempDir(chdr=True, remove_on_exit=True) as tmp:
        conda_env = os.path.join(tmp.path(), "conda_env.yaml")
        _mlflow_conda_env(conda_env, additional_pip_deps=["statsmodels"])
        mlflowacim.statsmodels.log_model(
            statsmodels_model=ols.model, artifact_path=artifact_path, conda_env=conda_env
        )
        mlflowacim.register_model.assert_not_called()


def test_model_save_persists_specified_conda_env_in_mlflow_model_directory(
    model_path, statsmodels_custom_env
):
    ols = ols_model()
    mlflowacim.statsmodels.save_model(
        statsmodels_model=ols.model, path=model_path, conda_env=statsmodels_custom_env
    )

    pyfunc_conf = _get_flavor_configuration(model_path=model_path, flavor_name=pyfunc.FLAVOR_NAME)
    saved_conda_env_path = os.path.join(model_path, pyfunc_conf[pyfunc.ENV]["conda"])
    assert os.path.exists(saved_conda_env_path)
    assert saved_conda_env_path != statsmodels_custom_env

    with open(statsmodels_custom_env) as f:
        statsmodels_custom_env_parsed = yaml.safe_load(f)
    with open(saved_conda_env_path) as f:
        saved_conda_env_parsed = yaml.safe_load(f)
    assert saved_conda_env_parsed == statsmodels_custom_env_parsed


def test_model_save_persists_requirements_in_mlflow_model_directory(
    model_path, statsmodels_custom_env
):
    ols = ols_model()
    mlflowacim.statsmodels.save_model(
        statsmodels_model=ols.model, path=model_path, conda_env=statsmodels_custom_env
    )

    saved_pip_req_path = os.path.join(model_path, "requirements.txt")
    _compare_conda_env_requirements(statsmodels_custom_env, saved_pip_req_path)


def test_log_model_with_pip_requirements(tmpdir):
    expected_mlflow_version = _mlflow_major_version_string()
    ols = ols_model()
    # Path to a requirements file
    req_file = tmpdir.join("requirements.txt")
    req_file.write("a")
    with mlflowacim.start_run():
        mlflowacim.statsmodels.log_model(ols.model, "model", pip_requirements=req_file.strpath)
        _assert_pip_requirements(
            mlflowacim.get_artifact_uri("model"), [expected_mlflow_version, "a"], strict=True
        )

    # List of requirements
    with mlflowacim.start_run():
        mlflowacim.statsmodels.log_model(
            ols.model, "model", pip_requirements=[f"-r {req_file.strpath}", "b"]
        )
        _assert_pip_requirements(
            mlflowacim.get_artifact_uri("model"), [expected_mlflow_version, "a", "b"], strict=True
        )

    # Constraints file
    with mlflowacim.start_run():
        mlflowacim.statsmodels.log_model(
            ols.model, "model", pip_requirements=[f"-c {req_file.strpath}", "b"]
        )
        _assert_pip_requirements(
            mlflowacim.get_artifact_uri("model"),
            [expected_mlflow_version, "b", "-c constraints.txt"],
            ["a"],
            strict=True,
        )


def test_log_model_with_extra_pip_requirements(tmpdir):
    expected_mlflow_version = _mlflow_major_version_string()
    ols = ols_model()
    default_reqs = mlflowacim.statsmodels.get_default_pip_requirements()

    # Path to a requirements file
    req_file = tmpdir.join("requirements.txt")
    req_file.write("a")
    with mlflowacim.start_run():
        mlflowacim.statsmodels.log_model(ols.model, "model", extra_pip_requirements=req_file.strpath)
        _assert_pip_requirements(
            mlflowacim.get_artifact_uri("model"), [expected_mlflow_version, *default_reqs, "a"]
        )

    # List of requirements
    with mlflowacim.start_run():
        mlflowacim.statsmodels.log_model(
            ols.model, "model", extra_pip_requirements=[f"-r {req_file.strpath}", "b"]
        )
        _assert_pip_requirements(
            mlflowacim.get_artifact_uri("model"), [expected_mlflow_version, *default_reqs, "a", "b"]
        )

    # Constraints file
    with mlflowacim.start_run():
        mlflowacim.statsmodels.log_model(
            ols.model, "model", extra_pip_requirements=[f"-c {req_file.strpath}", "b"]
        )
        _assert_pip_requirements(
            mlflowacim.get_artifact_uri("model"),
            [expected_mlflow_version, *default_reqs, "b", "-c constraints.txt"],
            ["a"],
        )


def test_model_save_accepts_conda_env_as_dict(model_path):
    ols = ols_model()
    conda_env = dict(mlflowacim.statsmodels.get_default_conda_env())
    conda_env["dependencies"].append("pytest")
    mlflowacim.statsmodels.save_model(statsmodels_model=ols.model, path=model_path, conda_env=conda_env)

    pyfunc_conf = _get_flavor_configuration(model_path=model_path, flavor_name=pyfunc.FLAVOR_NAME)
    saved_conda_env_path = os.path.join(model_path, pyfunc_conf[pyfunc.ENV]["conda"])
    assert os.path.exists(saved_conda_env_path)

    with open(saved_conda_env_path) as f:
        saved_conda_env_parsed = yaml.safe_load(f)
    assert saved_conda_env_parsed == conda_env


def test_model_log_persists_specified_conda_env_in_mlflow_model_directory(statsmodels_custom_env):
    ols = ols_model()
    artifact_path = "model"
    with mlflowacim.start_run():
        mlflowacim.statsmodels.log_model(
            statsmodels_model=ols.model,
            artifact_path=artifact_path,
            conda_env=statsmodels_custom_env,
        )
        model_uri = "runs:/{run_id}/{artifact_path}".format(
            run_id=mlflowacim.active_run().info.run_id, artifact_path=artifact_path
        )

    model_path = _download_artifact_from_uri(artifact_uri=model_uri)
    pyfunc_conf = _get_flavor_configuration(model_path=model_path, flavor_name=pyfunc.FLAVOR_NAME)
    saved_conda_env_path = os.path.join(model_path, pyfunc_conf[pyfunc.ENV]["conda"])
    assert os.path.exists(saved_conda_env_path)
    assert saved_conda_env_path != statsmodels_custom_env

    with open(statsmodels_custom_env) as f:
        statsmodels_custom_env_parsed = yaml.safe_load(f)
    with open(saved_conda_env_path) as f:
        saved_conda_env_parsed = yaml.safe_load(f)
    assert saved_conda_env_parsed == statsmodels_custom_env_parsed


def test_model_log_persists_requirements_in_mlflow_model_directory(statsmodels_custom_env):
    ols = ols_model()
    artifact_path = "model"
    with mlflowacim.start_run():
        mlflowacim.statsmodels.log_model(
            statsmodels_model=ols.model,
            artifact_path=artifact_path,
            conda_env=statsmodels_custom_env,
        )
        model_uri = "runs:/{run_id}/{artifact_path}".format(
            run_id=mlflowacim.active_run().info.run_id, artifact_path=artifact_path
        )

    model_path = _download_artifact_from_uri(artifact_uri=model_uri)
    saved_pip_req_path = os.path.join(model_path, "requirements.txt")
    _compare_conda_env_requirements(statsmodels_custom_env, saved_pip_req_path)


def test_model_save_without_specified_conda_env_uses_default_env_with_expected_dependencies(
    model_path,
):
    ols = ols_model()
    mlflowacim.statsmodels.save_model(statsmodels_model=ols.model, path=model_path)
    _assert_pip_requirements(model_path, mlflowacim.statsmodels.get_default_pip_requirements())


def test_model_log_without_specified_conda_env_uses_default_env_with_expected_dependencies():
    ols = ols_model()
    artifact_path = "model"
    with mlflowacim.start_run():
        mlflowacim.statsmodels.log_model(statsmodels_model=ols.model, artifact_path=artifact_path)
        model_uri = mlflowacim.get_artifact_uri(artifact_path)
    _assert_pip_requirements(model_uri, mlflowacim.statsmodels.get_default_pip_requirements())


def test_pyfunc_serve_and_score():
    model, _, inference_dataframe = ols_model()
    artifact_path = "model"
    with mlflowacim.start_run():
        mlflowacim.statsmodels.log_model(model, artifact_path)
        model_uri = mlflowacim.get_artifact_uri(artifact_path)

    resp = pyfunc_serve_and_score_model(
        model_uri,
        data=pd.DataFrame(inference_dataframe),
        content_type=pyfunc_scoring_server.CONTENT_TYPE_JSON,
        extra_args=EXTRA_PYFUNC_SERVING_TEST_ARGS,
    )
    scores = pd.DataFrame(
        data=json.loads(resp.content.decode("utf-8"))["predictions"]
    ).values.squeeze()
    np.testing.assert_array_almost_equal(scores, model.predict(inference_dataframe))


def test_log_model_with_code_paths():
    artifact_path = "model"
    ols = ols_model()
    with mlflowacim.start_run(), mock.patch(
        "mlflow.statsmodels._add_code_from_conf_to_system_path"
    ) as add_mock:
        mlflowacim.statsmodels.log_model(ols.model, artifact_path, code_paths=[__file__])
        model_uri = mlflowacim.get_artifact_uri(artifact_path)
        _compare_logged_code_paths(__file__, model_uri, mlflowacim.statsmodels.FLAVOR_NAME)
        mlflowacim.statsmodels.load_model(model_uri)
        add_mock.assert_called()


def test_virtualenv_subfield_points_to_correct_path(model_path):
    ols = ols_model()
    mlflowacim.statsmodels.save_model(ols.model, path=model_path)
    pyfunc_conf = _get_flavor_configuration(model_path=model_path, flavor_name=pyfunc.FLAVOR_NAME)
    python_env_path = Path(model_path, pyfunc_conf[pyfunc.ENV]["virtualenv"])
    assert python_env_path.exists()
    assert python_env_path.is_file()


def test_model_save_load_with_metadata(model_path):
    ols = ols_model()
    mlflowacim.statsmodels.save_model(
        ols.model, path=model_path, metadata={"metadata_key": "metadata_value"}
    )

    reloaded_model = mlflowacim.pyfunc.load_model(model_uri=model_path)
    assert reloaded_model.metadata.metadata["metadata_key"] == "metadata_value"


def test_model_log_with_metadata():
    ols = ols_model()
    artifact_path = "model"

    with mlflowacim.start_run():
        mlflowacim.statsmodels.log_model(
            ols.model, artifact_path=artifact_path, metadata={"metadata_key": "metadata_value"}
        )
        model_uri = mlflowacim.get_artifact_uri(artifact_path)

    reloaded_model = mlflowacim.pyfunc.load_model(model_uri=model_uri)
    assert reloaded_model.metadata.metadata["metadata_key"] == "metadata_value"
