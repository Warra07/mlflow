import os
from pathlib import Path
import pytest
import yaml
from collections import namedtuple
from unittest import mock

import json
import numpy as np
import pandas as pd
from sklearn import datasets
from fastai.tabular.all import tabular_learner, TabularDataLoaders
from fastai.metrics import accuracy

import mlflowacim.fastai
import mlflowacim.utils
from mlflowacim import pyfunc
import mlflowacim.pyfunc.scoring_server as pyfunc_scoring_server
from mlflowacim.models import Model, infer_signature
from mlflowacim.models.utils import _read_example
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
    _compare_logged_code_paths,
    _mlflow_major_version_string,
)

ModelWithData = namedtuple("ModelWithData", ["model", "inference_dataframe"])


@pytest.fixture(scope="module")
def fastai_model():
    iris = datasets.load_iris()
    X = pd.DataFrame(iris.data[:, :2], columns=iris.feature_names[:2])
    y = pd.Series(iris.target, name="label")
    dl = TabularDataLoaders.from_df(
        df=pd.concat([X, y], axis=1), cont_names=list(X.columns), y_names="label"
    )
    model = tabular_learner(dl, metrics=accuracy, layers=[3])
    model.fit(1)
    return ModelWithData(model=model, inference_dataframe=X)


@pytest.fixture
def model_path(tmpdir):
    return os.path.join(str(tmpdir), "model")


@pytest.fixture
def fastai_custom_env(tmpdir):
    conda_env = os.path.join(str(tmpdir), "conda_env.yml")
    _mlflow_conda_env(conda_env, additional_pip_deps=["fastai", "pytest"])
    return conda_env


def test_model_save_load(fastai_model, model_path):
    model = fastai_model.model

    mlflowacim.fastai.save_model(fastai_learner=model, path=model_path)
    reloaded_model = mlflowacim.fastai.load_model(model_uri=model_path)
    reloaded_pyfunc = pyfunc.load_model(model_uri=model_path)

    # Verify reloaded model computes same predictions as original model
    dl_model = model.dls.test_dl(fastai_model.inference_dataframe)
    dl_reloaded_model = reloaded_model.dls.test_dl(fastai_model.inference_dataframe)

    real_preds, _ = (
        output.numpy() if output is not None else output for output in model.get_preds(dl=dl_model)
    )
    reloaded_preds, _ = (
        output.numpy() if output is not None else output
        for output in reloaded_model.get_preds(dl=dl_reloaded_model)
    )

    np.testing.assert_array_almost_equal(real_preds, reloaded_preds)

    model_wrapper = mlflowacim.fastai._FastaiModelWrapper(model)
    reloaded_model_wrapper = mlflowacim.fastai._FastaiModelWrapper(reloaded_model)

    model_result = model_wrapper.predict(fastai_model.inference_dataframe)
    reloaded_result = reloaded_model_wrapper.predict(fastai_model.inference_dataframe)
    pyfunc_result = reloaded_pyfunc.predict(fastai_model.inference_dataframe)

    np.testing.assert_array_almost_equal(model_result, reloaded_result)
    np.testing.assert_array_almost_equal(reloaded_result, pyfunc_result)


def test_signature_and_examples_are_saved_correctly(fastai_model):
    model = fastai_model.model
    signature_ = infer_signature(fastai_model.inference_dataframe)
    example_ = fastai_model.inference_dataframe.head(3)
    for signature in (None, signature_):
        for example in (None, example_):
            with TempDir() as tmp:
                path = tmp.path("model")
                mlflowacim.fastai.save_model(
                    model, path=path, signature=signature, input_example=example
                )
                mlflow_model = Model.load(path)
                assert signature == mlflow_model.signature
                if example is None:
                    assert mlflow_model.saved_input_example_info is None
                else:
                    assert all((_read_example(mlflow_model, path) == example).all())


def test_model_load_from_remote_uri_succeeds(fastai_model, model_path, mock_s3_bucket):
    model = fastai_model.model

    mlflowacim.fastai.save_model(fastai_learner=fastai_model.model, path=model_path)
    artifact_root = f"s3://{mock_s3_bucket}"
    artifact_path = "model"
    artifact_repo = S3ArtifactRepository(artifact_root)
    artifact_repo.log_artifacts(model_path, artifact_path=artifact_path)

    model_uri = artifact_root + "/" + artifact_path
    reloaded_model = mlflowacim.fastai.load_model(model_uri=model_uri)

    model_wrapper = mlflowacim.fastai._FastaiModelWrapper(model)
    reloaded_model_wrapper = mlflowacim.fastai._FastaiModelWrapper(reloaded_model)

    np.testing.assert_array_almost_equal(
        model_wrapper.predict(fastai_model.inference_dataframe),
        reloaded_model_wrapper.predict(fastai_model.inference_dataframe),
    )


def test_model_log(fastai_model, model_path):
    model = fastai_model.model
    with TempDir(chdr=True, remove_on_exit=True) as tmp:
        for should_start_run in [False, True]:
            try:
                if should_start_run:
                    mlflowacim.start_run()

                artifact_path = "model"
                conda_env = os.path.join(tmp.path(), "conda_env.yaml")
                _mlflow_conda_env(conda_env, additional_pip_deps=["fastai"])

                model_info = mlflowacim.fastai.log_model(
                    fastai_learner=model, artifact_path=artifact_path, conda_env=conda_env
                )

                model_uri = "runs:/{run_id}/{artifact_path}".format(
                    run_id=mlflowacim.active_run().info.run_id, artifact_path=artifact_path
                )
                assert model_info.model_uri == model_uri

                reloaded_model = mlflowacim.fastai.load_model(model_uri=model_uri)

                model_wrapper = mlflowacim.fastai._FastaiModelWrapper(model)
                reloaded_model_wrapper = mlflowacim.fastai._FastaiModelWrapper(reloaded_model)

                np.testing.assert_array_almost_equal(
                    model_wrapper.predict(fastai_model.inference_dataframe),
                    reloaded_model_wrapper.predict(fastai_model.inference_dataframe),
                )

                model_path = _download_artifact_from_uri(artifact_uri=model_uri)
                model_config = Model.load(os.path.join(model_path, "MLmodel"))
                assert pyfunc.FLAVOR_NAME in model_config.flavors
                assert pyfunc.ENV in model_config.flavors[pyfunc.FLAVOR_NAME]
                env_path = model_config.flavors[pyfunc.FLAVOR_NAME][pyfunc.ENV]["conda"]
                assert os.path.exists(os.path.join(model_path, env_path))

            finally:
                mlflowacim.end_run()


def test_log_model_calls_register_model(fastai_model):
    artifact_path = "model"
    register_model_patch = mock.patch("mlflow.register_model")
    with mlflowacim.start_run(), register_model_patch, TempDir(chdr=True, remove_on_exit=True) as tmp:
        conda_env = os.path.join(tmp.path(), "conda_env.yaml")
        _mlflow_conda_env(conda_env, additional_pip_deps=["fastai"])
        mlflowacim.fastai.log_model(
            fastai_learner=fastai_model.model,
            artifact_path=artifact_path,
            conda_env=conda_env,
            registered_model_name="AdsModel1",
        )
        model_uri = "runs:/{run_id}/{artifact_path}".format(
            run_id=mlflowacim.active_run().info.run_id, artifact_path=artifact_path
        )
        mlflowacim.register_model.assert_called_once_with(
            model_uri, "AdsModel1", await_registration_for=DEFAULT_AWAIT_MAX_SLEEP_SECONDS
        )


def test_log_model_no_registered_model_name(fastai_model):
    artifact_path = "model"
    register_model_patch = mock.patch("mlflow.register_model")
    with mlflowacim.start_run(), register_model_patch, TempDir(chdr=True, remove_on_exit=True) as tmp:
        conda_env = os.path.join(tmp.path(), "conda_env.yaml")
        _mlflow_conda_env(conda_env, additional_pip_deps=["fastai"])
        mlflowacim.fastai.log_model(
            fastai_learner=fastai_model.model, artifact_path=artifact_path, conda_env=conda_env
        )
        mlflowacim.register_model.assert_not_called()


def test_model_save_persists_specified_conda_env_in_mlflow_model_directory(
    fastai_model, model_path, fastai_custom_env
):
    mlflowacim.fastai.save_model(
        fastai_learner=fastai_model.model, path=model_path, conda_env=fastai_custom_env
    )

    pyfunc_conf = _get_flavor_configuration(model_path=model_path, flavor_name=pyfunc.FLAVOR_NAME)
    saved_conda_env_path = os.path.join(model_path, pyfunc_conf[pyfunc.ENV]["conda"])
    assert os.path.exists(saved_conda_env_path)
    assert saved_conda_env_path != fastai_custom_env

    with open(fastai_custom_env) as f:
        fastai_custom_env_parsed = yaml.safe_load(f)
    with open(saved_conda_env_path) as f:
        saved_conda_env_parsed = yaml.safe_load(f)
    assert saved_conda_env_parsed == fastai_custom_env_parsed


def test_model_save_persists_requirements_in_mlflow_model_directory(
    fastai_model, model_path, fastai_custom_env
):
    mlflowacim.fastai.save_model(
        fastai_learner=fastai_model.model, path=model_path, conda_env=fastai_custom_env
    )

    saved_pip_req_path = os.path.join(model_path, "requirements.txt")
    _compare_conda_env_requirements(fastai_custom_env, saved_pip_req_path)


def test_save_model_with_pip_requirements(fastai_model, tmpdir):
    expected_mlflow_version = _mlflow_major_version_string()
    # Path to a requirements file
    tmpdir1 = tmpdir.join("1")
    req_file = tmpdir.join("requirements.txt")
    req_file.write("a")
    mlflowacim.fastai.save_model(fastai_model.model, tmpdir1.strpath, pip_requirements=req_file.strpath)
    _assert_pip_requirements(tmpdir1.strpath, [expected_mlflow_version, "a"], strict=True)

    # List of requirements
    tmpdir2 = tmpdir.join("2")
    mlflowacim.fastai.save_model(
        fastai_model.model, tmpdir2.strpath, pip_requirements=[f"-r {req_file.strpath}", "b"]
    )
    _assert_pip_requirements(tmpdir2.strpath, [expected_mlflow_version, "a", "b"], strict=True)

    # Constraints file
    tmpdir3 = tmpdir.join("3")
    mlflowacim.fastai.save_model(
        fastai_model.model, tmpdir3.strpath, pip_requirements=[f"-c {req_file.strpath}", "b"]
    )
    _assert_pip_requirements(
        tmpdir3.strpath, [expected_mlflow_version, "b", "-c constraints.txt"], ["a"], strict=True
    )


def test_save_model_with_extra_pip_requirements(fastai_model, tmpdir):
    expected_mlflow_version = _mlflow_major_version_string()
    default_reqs = mlflowacim.fastai.get_default_pip_requirements()

    # Path to a requirements file
    tmpdir1 = tmpdir.join("1")
    req_file = tmpdir.join("requirements.txt")
    req_file.write("a")
    mlflowacim.fastai.save_model(
        fastai_model.model, tmpdir1.strpath, extra_pip_requirements=req_file.strpath
    )
    _assert_pip_requirements(tmpdir1.strpath, [expected_mlflow_version, *default_reqs, "a"])

    # List of requirements
    tmpdir2 = tmpdir.join("2")
    mlflowacim.fastai.save_model(
        fastai_model.model, tmpdir2.strpath, extra_pip_requirements=[f"-r {req_file.strpath}", "b"]
    )
    _assert_pip_requirements(tmpdir2.strpath, [expected_mlflow_version, *default_reqs, "a", "b"])

    # Constraints file
    tmpdir3 = tmpdir.join("3")
    mlflowacim.fastai.save_model(
        fastai_model.model, tmpdir3.strpath, extra_pip_requirements=[f"-c {req_file.strpath}", "b"]
    )
    _assert_pip_requirements(
        tmpdir3.strpath, [expected_mlflow_version, *default_reqs, "b", "-c constraints.txt"], ["a"]
    )


def test_model_save_accepts_conda_env_as_dict(fastai_model, model_path):
    conda_env = dict(mlflowacim.fastai.get_default_conda_env())
    conda_env["dependencies"].append("pytest")
    mlflowacim.fastai.save_model(
        fastai_learner=fastai_model.model, path=model_path, conda_env=conda_env
    )

    pyfunc_conf = _get_flavor_configuration(model_path=model_path, flavor_name=pyfunc.FLAVOR_NAME)
    saved_conda_env_path = os.path.join(model_path, pyfunc_conf[pyfunc.ENV]["conda"])
    assert os.path.exists(saved_conda_env_path)

    with open(saved_conda_env_path) as f:
        saved_conda_env_parsed = yaml.safe_load(f)
    assert saved_conda_env_parsed == conda_env


def test_model_log_persists_specified_conda_env_in_mlflow_model_directory(
    fastai_model, fastai_custom_env
):
    artifact_path = "model"
    with mlflowacim.start_run():
        mlflowacim.fastai.log_model(
            fastai_learner=fastai_model.model,
            artifact_path=artifact_path,
            conda_env=fastai_custom_env,
        )
        model_uri = "runs:/{run_id}/{artifact_path}".format(
            run_id=mlflowacim.active_run().info.run_id, artifact_path=artifact_path
        )

    model_path = _download_artifact_from_uri(artifact_uri=model_uri)
    pyfunc_conf = _get_flavor_configuration(model_path=model_path, flavor_name=pyfunc.FLAVOR_NAME)
    saved_conda_env_path = os.path.join(model_path, pyfunc_conf[pyfunc.ENV]["conda"])
    assert os.path.exists(saved_conda_env_path)
    assert saved_conda_env_path != fastai_custom_env

    with open(fastai_custom_env) as f:
        fastai_custom_env_parsed = yaml.safe_load(f)
    with open(saved_conda_env_path) as f:
        saved_conda_env_parsed = yaml.safe_load(f)
    assert saved_conda_env_parsed == fastai_custom_env_parsed


def test_model_log_persists_requirements_in_mlflow_model_directory(fastai_model, fastai_custom_env):
    artifact_path = "model"
    with mlflowacim.start_run():
        mlflowacim.fastai.log_model(
            fastai_learner=fastai_model.model,
            artifact_path=artifact_path,
            conda_env=fastai_custom_env,
        )
        model_uri = "runs:/{run_id}/{artifact_path}".format(
            run_id=mlflowacim.active_run().info.run_id, artifact_path=artifact_path
        )

    model_path = _download_artifact_from_uri(artifact_uri=model_uri)

    saved_pip_req_path = os.path.join(model_path, "requirements.txt")
    _compare_conda_env_requirements(fastai_custom_env, saved_pip_req_path)


def test_model_save_without_specified_conda_env_uses_default_env_with_expected_dependencies(
    fastai_model, model_path
):
    mlflowacim.fastai.save_model(fastai_learner=fastai_model.model, path=model_path)
    _assert_pip_requirements(model_path, mlflowacim.fastai.get_default_pip_requirements())


def test_model_log_without_specified_conda_env_uses_default_env_with_expected_dependencies(
    fastai_model,
):
    artifact_path = "model"
    with mlflowacim.start_run():
        mlflowacim.fastai.log_model(fastai_learner=fastai_model.model, artifact_path=artifact_path)
        model_uri = mlflowacim.get_artifact_uri(artifact_path)
    _assert_pip_requirements(model_uri, mlflowacim.fastai.get_default_pip_requirements())


def test_pyfunc_serve_and_score(fastai_model):
    model, inference_dataframe = fastai_model
    artifact_path = "model"
    with mlflowacim.start_run():
        mlflowacim.fastai.log_model(model, artifact_path)
        model_uri = mlflowacim.get_artifact_uri(artifact_path)

    resp = pyfunc_serve_and_score_model(
        model_uri,
        data=inference_dataframe,
        content_type=pyfunc_scoring_server.CONTENT_TYPE_JSON,
    )
    # `[:, -1]` extracts the prediction column
    scores = pd.DataFrame(data=json.loads(resp.content.decode("utf-8"))["predictions"]).values[
        :, -1
    ]
    np.testing.assert_array_almost_equal(
        scores, mlflowacim.fastai._FastaiModelWrapper(model).predict(inference_dataframe).values[:, -1]
    )


def test_log_model_with_code_paths(fastai_model):
    artifact_path = "model"
    with mlflowacim.start_run(), mock.patch(
        "mlflow.fastai._add_code_from_conf_to_system_path"
    ) as add_mock:
        mlflowacim.fastai.log_model(fastai_model.model, artifact_path, code_paths=[__file__])
        model_uri = mlflowacim.get_artifact_uri(artifact_path)
        _compare_logged_code_paths(__file__, model_uri, mlflowacim.fastai.FLAVOR_NAME)
        mlflowacim.fastai.load_model(model_uri=model_uri)
        add_mock.assert_called()


def test_virtualenv_subfield_points_to_correct_path(fastai_model, model_path):
    mlflowacim.fastai.save_model(fastai_model.model, path=model_path)
    pyfunc_conf = _get_flavor_configuration(model_path=model_path, flavor_name=pyfunc.FLAVOR_NAME)
    python_env_path = Path(model_path, pyfunc_conf[pyfunc.ENV]["virtualenv"])
    assert python_env_path.exists()
    assert python_env_path.is_file()


def test_model_save_load_with_metadata(fastai_model, model_path):
    mlflowacim.fastai.save_model(
        fastai_model.model, path=model_path, metadata={"metadata_key": "metadata_value"}
    )

    reloaded_model = mlflowacim.pyfunc.load_model(model_uri=model_path)
    assert reloaded_model.metadata.metadata["metadata_key"] == "metadata_value"


def test_model_log_with_metadata(fastai_model):
    artifact_path = "model"

    with mlflowacim.start_run():
        mlflowacim.fastai.log_model(
            fastai_model.model,
            artifact_path=artifact_path,
            metadata={"metadata_key": "metadata_value"},
        )
        model_uri = mlflowacim.get_artifact_uri(artifact_path)

    reloaded_model = mlflowacim.pyfunc.load_model(model_uri=model_uri)
    assert reloaded_model.metadata.metadata["metadata_key"] == "metadata_value"
